import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core');
const {PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,runId,socket,output,baselines]=process.argv.slice(2);
const browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
  const page=await browser.newPage({viewport:{width:1280,height:960},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`${url}#run/${runId}`);
  const card=page.locator('[data-region="run-setup"]'),graph=card.locator('[data-region="loading-layout"]');
  await graph.waitFor();
  const deck=graph.locator('[data-region="loading-deck"]');
  await deck.waitFor();
  if(await deck.locator('.setup-deck-track').count()!==54) throw new Error('Missing full track ruler');
  const carrier=deck.locator('[data-carrier-id="plates"]');
  if(await carrier.getAttribute('data-track-start')!=='4' || await carrier.getAttribute('data-track-span')!=='6')
    throw new Error('Carrier footprint does not match driver geometry');
  await deck.getByRole('button',{name:/^Inspect deck item destination_plate /}).click();

  const before=await graph.getAttribute('data-setup-fingerprint');
  const plate=graph.getByRole('button',{name:/^Inspect destination_plate /});
  await plate.focus();await plate.press('Enter');
  const used=()=>graph.locator('[data-well][data-required="true"]').evaluateAll(nodes=>nodes.map(node=>node.dataset.well));
  if(JSON.stringify(await used())!==JSON.stringify(['A1','A2','A3'])) throw new Error('Wrong required wells');
  await graph.getByRole('button',{name:/^Inspect source_vessel /}).click();
  await graph.locator('[data-region="loading-inspector"]').getByRole('heading',{name:'source',exact:true}).waitFor();
  await card.getByRole('button',{name:'Start loading',exact:true}).click();
  const check=card.getByRole('checkbox',{name:'I loaded every item according to this plan',exact:true});
  await check.check();
  const confirm=card.getByRole('button',{name:'Confirm loading and run',exact:true});
  if(!await confirm.isEnabled()) throw new Error('Current plan was not acknowledged');
  const revised=spawnSync(process.env.CULSMA_OS_TEST_PYTHON,['-m','tests.support.console.loading_layout_mcp',socket,runId],
    {env:{...process.env,PYTHONPATH:`${process.env.CULSMA_OS_MCP_SDK_PATH}:${process.cwd()}/src`},encoding:'utf8',timeout:30000});
  if(revised.status!==0) throw new Error(revised.stderr);
  const after=JSON.parse(revised.stdout).after;
  await page.waitForFunction(fingerprint=>document.querySelector('[data-region="loading-layout"]')?.dataset.setupFingerprint===fingerprint,after);
  if(await check.isChecked() || await confirm.isEnabled()) throw new Error('Old physical acknowledgement survived changed placement');
  await graph.getByRole('button',{name:/^Inspect source_other /}).getByText('source',{exact:true}).waitFor();
  await graph.getByRole('button',{name:/^Inspect source_vessel /}).getByText('diluent',{exact:true}).waitFor();
  await graph.getByRole('button',{name:/^Inspect destination_plate /}).click();
  await page.locator('#operation-status').evaluate(node=>{node.style.visibility='hidden';});
  for(const width of [1280,390]) {
    await page.setViewportSize({width,height:960});
    const actual=await graph.screenshot({path:`${output}/loading-layout-${width}.png`,animations:'disabled'});
    const baseline=`${baselines}/loading-layout-${width}.png`;
    if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1') writeFileSync(baseline,actual);
    else {
      const ref=PNG.sync.read(readFileSync(baseline)),image=PNG.sync.read(actual);
      if(ref.width!==image.width || ref.height!==image.height) throw new Error(`Layout golden dimensions changed at ${width}`);
      if(pixelmatch(ref.data,image.data,null,image.width,image.height,{threshold:.1})>image.width*image.height*.001)
        throw new Error(`Layout golden pixels changed at ${width}`);
    }
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error(`Page overflow at ${width}`);
  }
  await page.locator('#operation-status').evaluate(node=>{node.style.removeProperty('visibility');});
  await page.setViewportSize({width:1280,height:960});
  await check.check();await confirm.click();
  await page.waitForFunction(()=>document.querySelector('#content')?.dataset.runState==='completed');
  if(errors.length) throw new Error(errors.join('\n'));
  console.log(JSON.stringify({before,after,completed:true,required_wells:await used()}));
} finally {await browser.close();}

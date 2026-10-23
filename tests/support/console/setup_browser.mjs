import {createRequire} from 'node:module';
import {readFileSync, writeFileSync, existsSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core');
const {PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,runId,socket,screenshot,baseline]=process.argv.slice(2);
const browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
  const page=await browser.newPage({viewport:{width:1280,height:960},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`${url}#run/${runId}`);
  const card=page.locator('[data-region="run-setup"]');
  await card.getByRole('heading',{name:'Prepare and load'}).waitFor();
  const before=await card.getAttribute('data-setup-fingerprint');
  await card.getByText('Placement preferences',{exact:true}).click();
  await card.locator('[data-field="/setup/entry.s0::alloc/mode"]').selectOption('fixed');
  // External AI changes the shared plan over the actual stdio MCP transport.
  const mcp=spawnSync(process.env.CULSMA_OS_TEST_PYTHON,['-m','tests.support.console.mcp_client',socket,runId],
    {env:{...process.env,PYTHONPATH:`${process.env.CULSMA_OS_MCP_SDK_PATH}:${process.cwd()}/src`},encoding:'utf8',timeout:30000});
  if(mcp.status!==0) throw new Error(mcp.stderr);
  const after=JSON.parse(mcp.stdout).after;
  if(before===after) throw new Error('MCP did not revise the plan');
  await page.waitForFunction(fingerprint=>document.querySelector('[data-region="run-setup"]')?.dataset.setupFingerprint===fingerprint,after);
  await card.getByText('local-mcp-process',{exact:true}).first().waitFor();
  await card.getByText('The shared plan changed. Reload current preferences before editing.',{exact:true}).waitFor();
  await card.getByRole('button',{name:'Reload current preferences',exact:true}).click();
  await card.locator('[data-field="/setup/entry.s0::alloc/mode"]').waitFor();
  await card.getByText('Placement preferences',{exact:true}).click();
  // Human starts loading and explicitly attests the exact current plan.
  await card.getByRole('button',{name:'Begin loading · reserve station',exact:true}).click();
  const confirm=card.getByRole('button',{name:'Confirm loaded · allow execution',exact:true});
  await confirm.waitFor();
  if(await confirm.isEnabled()) throw new Error('Physical acknowledgement bypass');
  await card.getByText('Station reserved. Load every item above before confirming.',{exact:true}).waitFor();
  // Keep the golden free of random request identities; the records themselves remain visible in the UI.
  await page.locator('#operation-status').evaluate(node=>{node.style.visibility='hidden';});
  const png=await card.screenshot({path:screenshot,animations:'disabled',maskColor:'#e7edf4',mask:[card.locator('[data-region="setup-activity"] tbody tr td:last-child')]});
  await page.locator('#operation-status').evaluate(node=>{node.style.removeProperty('visibility');});
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN!=='1') {
    if(!existsSync(baseline)) throw new Error('Reviewed loading-screen golden is missing');
    const reference=PNG.sync.read(readFileSync(baseline));const actual=PNG.sync.read(png);
    if(reference.width!==actual.width||reference.height!==actual.height) throw new Error('Golden dimensions changed');
    const diff=new PNG({width:actual.width,height:actual.height});
    const changed=pixelmatch(reference.data,actual.data,diff.data,actual.width,actual.height,{threshold:0.1});
    if(changed>actual.width*actual.height*.001) {
      writeFileSync(screenshot.replace('.png','-diff.png'),PNG.sync.write(diff));
      throw new Error(`Loading-screen golden changed: ${changed} pixels`);
    }
  }
  await card.getByRole('checkbox',{name:'I loaded every item according to this plan',exact:true}).check();
  await confirm.click();
  await page.waitForFunction(()=>document.querySelector('#content')?.dataset.runState==='completed');
  if(errors.length) throw new Error(errors.join('\n'));
  console.log(JSON.stringify({before,after,completed:true,screenshot}));
} finally {await browser.close();}

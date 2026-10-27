import {readFileSync,writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core'),{PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url]=process.argv.slice(2),browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1280,height:960}}),errors=[],commands=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST' && ['submit','begin','confirm'].includes(r.postDataJSON()?.action))commands.push(r.postDataJSON().action);});
 await page.goto(url+'#station');
 await page.getByRole('combobox',{name:'Experiment',exact:true}).selectOption('transfer.culs');
 await page.getByRole('heading',{name:'Experiment requirements',exact:true}).waitFor();
 if(commands.length)throw new Error('Preview submitted an experiment');
 // Switching away clears the previous plan without creating a run.
 await page.getByRole('combobox',{name:'Experiment',exact:true}).selectOption({label:'Choose a protocol…'});
 if(await page.locator('[data-region="experiment-requirements"]').count())throw new Error('Old preview survived selection change');
 await page.getByRole('combobox',{name:'Experiment',exact:true}).selectOption('transfer.culs');
 await page.getByRole('button',{name:'Prepare experiment',exact:true}).waitFor();
 if(commands.length)throw new Error('Reopening submitted a run');
 const preview=page.locator('[data-region="experiment-requirements"]');
 await preview.locator('[data-region="loading-layout"]').waitFor();
 for(const width of [1280,390]) {
  await page.setViewportSize({width,height:960});
  const png=await page.locator('[data-region="workstation-program"]').screenshot({path:`run-artifacts/ui-tests/experiment-preview-${width}.png`,animations:'disabled'});
  const baseline=`tests/modules/console/goldens/experiment-preview-${width}.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(baseline,png);
  else {const ref=PNG.sync.read(readFileSync(baseline)),img=PNG.sync.read(png);
   if(ref.width!==img.width || ref.height!==img.height || pixelmatch(ref.data,img.data,null,img.width,img.height,{threshold:.1})>img.width*img.height*.001)
    throw new Error(`Experiment preview golden changed at ${width}`);
  }
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error(`Preview overflow at ${width}`);
 }
 await page.setViewportSize({width:1280,height:960});
 const checklist=preview.locator('.loading-item');
 await checklist.first().click();
 const item=await checklist.first().getAttribute('data-labware-id');
 if(await preview.locator('[data-region="loading-inspector"]').getAttribute('data-labware-id')!==item)throw new Error('Checklist selection not reflected in inspector');
 const deck=preview.locator('.setup-deck-scroll');
 const scroll=await deck.evaluate(node=>{node.scrollLeft=90;return node.scrollLeft;});
 await checklist.last().click();
 if(Math.abs(await deck.evaluate(node=>node.scrollLeft)-scroll)>1)throw new Error('Selection reset horizontal deck scroll');
 // A backend read failure offers retry; it cannot leave an actionable old preview.
 await page.route('**/api/v1/programs',async route=>{
  if(route.request().method()==='POST' && route.request().postDataJSON()?.action==='preview')
   return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'TEST_PREVIEW_UNAVAILABLE'}})});
  await route.continue();
 });
 await page.getByRole('button',{name:'Refresh requirements',exact:true}).click();
 await page.getByText(/Unable to prepare requirements:/).waitFor();
 if(await page.getByRole('button',{name:'Prepare experiment',exact:true}).count())throw new Error('Failed preview left run enabled');
 await page.unroute('**/api/v1/programs');
 await page.getByRole('button',{name:'Refresh requirements',exact:true}).click();
 await page.getByRole('button',{name:'Prepare experiment',exact:true}).waitFor();
 await page.getByRole('button',{name:'Prepare experiment',exact:true}).click();
 const setup=page.locator('[data-region="run-setup"]');
 await setup.getByRole('button',{name:'Start loading',exact:true}).waitFor();
 const runId=await page.locator('#content').getAttribute('data-run-id');
 if(!runId) throw new Error('No selected run identity');
 if(await page.getByRole('heading',{name:'Workstation',exact:true}).count()!==1)throw new Error('Submission left workstation');
 await page.getByRole('heading',{name:'Run controls',exact:true}).waitFor();
 await setup.getByRole('button',{name:'Start loading',exact:true}).click();
 const confirm=setup.getByRole('button',{name:'Confirm loading and run',exact:true});await confirm.waitFor();
 if(await confirm.isEnabled())throw new Error('Loading confirmation gate bypassed');
 await setup.getByRole('checkbox',{name:'I loaded every item according to this plan',exact:true}).check();
 await confirm.click();
 await page.waitForFunction(()=>document.querySelector('#content')?.dataset.runState==='completed');
 const material=page.locator('#run-panel-results').getByRole('table');
 await material.getByRole('cell',{name:'source',exact:true}).waitFor();
 if(await material.getByRole('cell',{name:'100',exact:true}).count()!==2)throw new Error('Wrong transfer material result');
 if(JSON.stringify(commands)!==JSON.stringify(['submit','begin','confirm']))throw new Error('Unexpected command sequence: '+commands);
 // Re-enter the result through history; this must not repeat any command.
 await page.getByRole('navigation',{name:'Console pages'}).getByRole('link',{name:'Workstation',exact:true}).click();
 await page.getByText('Runs and history',{exact:true}).click();
 await page.locator('[data-region="workstation-runs-host"]').getByRole('link',{name:runId,exact:true}).click();
 await page.getByRole('heading',{name:'OS-registered material',exact:true}).waitFor();
 if(commands.length!==3)throw new Error('History replayed an operation');
 if(errors.length)throw new Error(errors.join('\n'));
 console.log(JSON.stringify({run_id:runId,completed:true,commands}));
} finally {await browser.close();}

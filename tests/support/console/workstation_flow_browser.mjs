import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core'),{PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,programRoot]=process.argv.slice(2),browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
async function golden(page,locator,name,width) {
 await page.setViewportSize({width,height:960});
 const png=await locator.screenshot({path:`run-artifacts/ui-tests/${name}-${width}.png`,animations:'disabled'});
 const file=`tests/modules/console/goldens/${name}-${width}.png`;
 if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(file,png);
 else {const ref=PNG.sync.read(readFileSync(file)),img=PNG.sync.read(png);
  if(ref.width!==img.width || ref.height!==img.height || pixelmatch(ref.data,img.data,null,img.width,img.height,{threshold:.1})>img.width*img.height*.001)
   throw new Error(`${name} golden changed at ${width}`);
 }
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error(`Overflow at ${width}`);
}
try {
 const page=await browser.newPage({viewport:{width:1280,height:960}}),errors=[],commands=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST' && ['start','submit','begin','confirm'].includes(r.postDataJSON()?.action))commands.push(r.postDataJSON().action);});
 await page.goto(url+'#station');
 const files=page.getByRole('complementary',{name:'Program files'});
 const file=files.getByRole('button',{name:'standard-curve/transfer.culs',exact:true});
 await file.click();
 await page.getByRole('heading',{name:'Protocol preview',exact:true}).waitFor();
 if(await file.getAttribute('aria-pressed')!=='true' || !await file.evaluate(node=>node===document.activeElement))throw new Error('File selection lost highlight or keyboard focus');
 if(commands.length)throw new Error('Single click started an experiment');
 await page.locator('.program-location').evaluate(node=>node.textContent='Culsma/projects');
 for(const width of [1280,390])await golden(page,page.locator('[data-region="workstation-main"]'),'experiment-preview',width);
 await page.setViewportSize({width:1280,height:960});
 await files.getByRole('button',{name:'invalid.culs',exact:true}).click();
 await page.getByText('This protocol needs correction before it can run.',{exact:true}).waitFor();
 if(commands.length)throw new Error('Invalid source started an experiment');
 // Failed checks are returned immediately, with no run admission or loading clicks.
 await file.click();
 await page.getByRole('heading',{name:'Protocol preview',exact:true}).waitFor();
 await page.route('**/api/v1/programs',async route=>{
  if(route.request().method()==='POST' && route.request().postDataJSON()?.action==='preview')
   return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'TEST_PREVIEW_UNAVAILABLE'}})});
  await route.continue();
 });
 await page.getByRole('button',{name:'Run protocol',exact:true}).click();
 await page.getByText(/Unable to prepare requirements:/).waitFor();
 if(commands.length)throw new Error('Failed preparation admitted an experiment');
 await page.unroute('**/api/v1/programs');
 // A fresh double-click advances preparation and simulation loading without any other click.
 await page.reload();
 await file.dblclick();
 await page.waitForFunction(()=>document.querySelector('#content')?.dataset.runState==='completed');
 const runId=await page.locator('#content').getAttribute('data-run-id');
 if(!runId)throw new Error('Missing run identity');
 await page.getByRole('heading',{name:'Experiment result',exact:true}).waitFor();
 const material=page.locator('#run-panel-results').getByRole('table');
 await material.getByRole('cell',{name:'source',exact:true}).waitFor();
 if(await material.getByRole('cell',{name:'100',exact:true}).count()!==2)throw new Error('Wrong registered transfer result');
 if(JSON.stringify(commands)!==JSON.stringify(['start']))throw new Error('Expected exactly one start: '+commands);
 const placement=await page.evaluate(()=>({
  outcome:document.querySelector('[data-region="run-outcome"]').getBoundingClientRect().top,
  material:document.querySelector('#run-panel-results').getBoundingClientRect().top,
  layout:document.querySelector('[data-region="workstation-layout-host"]').getBoundingClientRect().top,
  height:innerHeight
 }));
 if(placement.outcome< -1 || placement.outcome>200 || placement.material>=placement.height || placement.material>=placement.layout)
  throw new Error('Results were not immediately visible before the layout: '+JSON.stringify(placement));
 await page.locator('[data-region="workstation-run-host"]').getByText(runId,{exact:true}).evaluate(node=>node.textContent='example-run-id');
 for(const width of [1280,390])await golden(page,page.locator('[data-region="workstation-run-host"]'),'experiment-result',width);
 // History and refreshing newly copied files must never repeat execution.
 await page.setViewportSize({width:1280,height:960});
 const navigation=page.getByRole('navigation',{name:'Console pages'});
 await navigation.getByRole('link',{name:'Workstation',exact:true}).click();
 await page.getByText('Runs and history',{exact:true}).click();
 await page.locator('[data-region="workstation-runs-host"]').getByRole('link',{name:runId,exact:true}).click();
 await page.getByRole('heading',{name:'Experiment result',exact:true}).waitFor();
 await navigation.getByRole('link',{name:'Workstation',exact:true}).click();
 mkdirSync(`${programRoot}/new-project`);
 writeFileSync(`${programRoot}/new-project/copied.culs`,readFileSync(`${programRoot}/transfer.culs`));
 await files.getByRole('button',{name:'Refresh files',exact:true}).click();
 await files.getByRole('button',{name:'new-project/copied.culs',exact:true}).waitFor();
 if(commands.length!==1)throw new Error('History or refresh replayed execution');
 if(errors.length)throw new Error(errors.join('\n'));
 console.log(JSON.stringify({run_id:runId,completed:true,commands}));
} finally {await browser.close();}

import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core'),{PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,runId,output,baselines]=process.argv.slice(2);
const browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1280,height:960}}),errors=[],writes=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(request.method()==='POST') {
  const body=request.postDataJSON();if(['submit','confirm','begin','revise','apply','save','create'].includes(body?.action)) writes.push(body.action);
 }});
 await page.goto(`${url}#run/${runId}`);
 const nav=page.getByRole('navigation',{name:'Console pages'});
 await page.getByRole('heading',{name:'Load the experiment',exact:true}).waitFor();
 if(JSON.stringify(await nav.getByRole('link').allTextContents())!==JSON.stringify(['Workstation','System Settings','System Info'])) throw new Error('Expected exactly three main destinations');
 if(await page.getByRole('tablist',{name:'Run stages'}).count()) throw new Error('Run stages still split into pages');
 await page.getByRole('heading',{name:'Run controls',exact:true}).waitFor();
 await page.getByRole('heading',{name:'OS-registered material',exact:true}).waitFor();
 const fingerprint=await page.locator('[data-region="run-setup"]').getAttribute('data-setup-fingerprint');
 if(await page.getByRole('heading',{name:'Execution evidence',exact:true}).isVisible()) throw new Error('Raw evidence is not collapsed');
 await page.getByText('Execution evidence and receipts',{exact:true}).click();
 await page.getByRole('heading',{name:'Execution evidence',exact:true}).waitFor();
 await page.getByText('Station state and resources',{exact:true}).click();
 await page.getByRole('heading',{name:'Station reservations',exact:true}).waitFor();
 await nav.getByRole('link',{name:'Workstation',exact:true}).click();
 await page.getByRole('combobox',{name:'Experiment',exact:true}).waitFor();
 await page.getByRole('link',{name:'System Settings: rack layout',exact:true}).waitFor();
 // Force several station snapshots while the actual deck is horizontally scrolled.
 await page.setViewportSize({width:900,height:960});
 const scroll=page.locator('[data-region="workstation-layout"] .setup-deck-scroll');
 const position=await scroll.evaluate(node=>{node.scrollLeft=140;return node.scrollLeft;});
 if(position<10) throw new Error('Test deck did not scroll');
 for(let i=0;i<2;i++) {
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#content')?.getAttribute('aria-busy')==='false');
  if(Math.abs(await scroll.evaluate(node=>node.scrollLeft)-position)>1) throw new Error('Refresh reset deck scroll');
 }
 await page.setViewportSize({width:1280,height:960});
 await nav.getByRole('link',{name:'System Settings',exact:true}).click();
 await page.getByText('Advanced · configuration presets and JSON',{exact:true}).waitFor();
 await nav.getByRole('link',{name:'System Info',exact:true}).click();
 await page.getByRole('heading',{name:'Configured equipment',exact:true}).waitFor();
 const sections=page.getByRole('navigation',{name:'System information sections'});
 for(const [label,heading] of [['Drivers and Capabilities','Installed drivers and capabilities'],
  ['Runtime Environment','Declared runtime environment'],['Service and Connection','Agent and hardware connection'],['Platform and Equipment','Configured equipment']]) {
  await sections.getByRole('link',{name:label,exact:true}).click();
  await page.getByRole('heading',{name:heading,exact:true}).waitFor();
  if(await page.locator('#content input,#content select,#content textarea').count()) throw new Error('System information has editable fields');
 }
 await nav.getByRole('link',{name:'Workstation',exact:true}).click();
 await page.getByText('Runs and history',{exact:true}).click();
 await page.locator('[data-region="workstation-runs-host"]').getByRole('link',{name:runId,exact:true}).click();
 await page.getByRole('heading',{name:'Load the experiment',exact:true}).waitFor();
 if(await page.locator('[data-region="run-setup"]').getAttribute('data-setup-fingerprint')!==fingerprint) throw new Error('Navigation changed loading plan');
 for(const width of [1280,390]) {
  await page.setViewportSize({width,height:960});
  if(width===390) await page.getByRole('button',{name:'Navigation',exact:true}).click();
  const actual=await page.locator('.sidebar').screenshot({path:`${output}/navigation-${width}.png`,animations:'disabled'});
  const file=`${baselines}/navigation-${width}.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1') writeFileSync(file,actual);
  else {const ref=PNG.sync.read(readFileSync(file)),image=PNG.sync.read(actual);
   if(ref.width!==image.width || ref.height!==image.height || pixelmatch(ref.data,image.data,null,image.width,image.height,{threshold:.1})>image.width*image.height*.001)
    throw new Error(`Navigation golden changed at ${width}`);
  }
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error(`Overflow at ${width}`);
 }
 if(writes.length) throw new Error('Navigation issued commands: '+writes.join(', '));
 if(errors.length) throw new Error(errors.join('\n'));
 console.log(JSON.stringify({single_workstation:true,system_read_only:true,navigation_writes:writes.length,loading_plan_unchanged:true}));
} finally {await browser.close();}

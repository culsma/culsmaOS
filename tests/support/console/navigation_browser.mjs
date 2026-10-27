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
 const tabs=page.getByRole('tablist',{name:'Run stages'}),nav=page.getByRole('navigation',{name:'Console pages'});
 await tabs.getByRole('tab',{name:'Preparation',exact:true}).waitFor();
 if(await tabs.getByRole('tab',{name:'Preparation'}).getAttribute('aria-selected')!=='true') throw new Error('Wrong initial run stage');
 const fingerprint=await page.locator('[data-region="run-setup"]').getAttribute('data-setup-fingerprint');
 await tabs.getByRole('tab',{name:'Preparation',exact:true}).focus();
 await tabs.getByRole('tab',{name:'Preparation',exact:true}).press('ArrowRight');
 await page.locator('#run-panel-execution').getByRole('heading',{name:'Run controls',exact:true}).waitFor();
 if(await page.locator('#run-panel-preparation').isVisible()) throw new Error('Preparation remained on execution page');
 await tabs.getByRole('tab',{name:'Results',exact:true}).click();
 await page.getByRole('heading',{name:'OS-registered material',exact:true}).waitFor();
 if(await page.getByRole('heading',{name:'Execution evidence',exact:true}).isVisible()) throw new Error('Raw evidence is not collapsed');
 await page.getByText('Execution evidence and receipts',{exact:true}).click();
 await page.getByRole('heading',{name:'Execution evidence',exact:true}).waitFor();
 await nav.getByRole('link',{name:'Current State',exact:true}).click();
 await page.getByRole('heading',{name:'Station reservations',exact:true}).waitFor();
 await nav.getByRole('link',{name:'Overview',exact:true}).click();
 await page.getByRole('link',{name:'Adjust layout settings',exact:true}).waitFor();
 await nav.getByRole('link',{name:'Layout',exact:true}).click();
 await page.getByText('Advanced · configuration presets and JSON',{exact:true}).waitFor();
 for(const [label,heading] of [['Platform and Equipment','Configured equipment'],['Drivers and Capabilities','Installed drivers and capabilities'],
  ['Runtime Environment','Declared runtime environment'],['Service and Connection','Agent and hardware connection']]) {
  await nav.getByRole('link',{name:label,exact:true}).click();
  await page.getByRole('heading',{name:heading,exact:true}).waitFor();
  if(await page.locator('#content input,#content select,#content textarea').count()) throw new Error('System information has editable fields');
 }
 await nav.getByRole('link',{name:'Run History',exact:true}).click();
 await page.locator('#content').getByRole('heading',{name:'Run History',exact:true}).waitFor();
 if(await page.locator('#content').getByRole('link',{name:runId,exact:true}).count()) throw new Error('Pending run appeared in history');
 await nav.getByRole('link',{name:'Active Runs and Queue',exact:true}).click();
 await page.locator('#content').getByRole('link',{name:runId,exact:true}).click();
 await page.locator('#run-panel-preparation').getByRole('heading',{name:'Prepare and load',exact:true}).waitFor();
 if(await page.locator('[data-region="run-setup"]').getAttribute('data-setup-fingerprint')!==fingerprint) throw new Error('Navigation changed loading plan');
 await nav.getByRole('link',{name:'New Run',exact:true}).click();
 await page.getByRole('button',{name:'Check program',exact:true}).waitFor();
 await nav.getByRole('link',{name:'Active Runs and Queue',exact:true}).click();
 await page.locator('#content').getByRole('link',{name:runId,exact:true}).click();
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
 console.log(JSON.stringify({stages:true,system_read_only:true,navigation_writes:writes.length,loading_plan_unchanged:true}));
} finally {await browser.close();}

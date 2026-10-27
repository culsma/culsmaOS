import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core'),{PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,output,baselines]=process.argv.slice(2),browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],actions=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(request.method()==='POST')actions.push(request.postDataJSON()?.action);});
 await page.goto(url+'#configuration');
 const settings=page.locator('[data-region="carrier-settings"]');
 await settings.getByRole('combobox',{name:'Installed rack',exact:true}).selectOption('carrier:PREVIEW_T37_38_4R200');
 await settings.getByRole('combobox',{name:'Replacement rack',exact:true}).selectOption('RGT_CAR_5R60_A00');
 await settings.getByRole('button',{name:'Check rack replacement',exact:true}).click();
 await settings.getByRole('heading',{name:'Checked rack replacement · not applied',exact:true}).waitFor();
 if(actions.includes('apply') || actions.includes('submit'))throw new Error('Checking changed active configuration or started a run');
 for(const width of [1440,390]) {
  await page.setViewportSize({width,height:1000});
  await page.waitForFunction(()=>{const viewport=document.querySelector('[data-region="carrier-proposal"] .setup-deck-scroll'),frame=viewport?.querySelector('[data-highlighted=true]');if(!frame)return false;const a=viewport.getBoundingClientRect(),b=frame.getBoundingClientRect();return b.left>=a.left && b.right<=a.right;});
  const image=await settings.screenshot({path:`${output}/carrier-settings-${width}.png`,animations:'disabled'});
  const file=`${baselines}/carrier-settings-${width}.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(file,image);
  else {const ref=PNG.sync.read(readFileSync(file)),actual=PNG.sync.read(image);
   if(ref.width!==actual.width || ref.height!==actual.height || pixelmatch(ref.data,actual.data,null,actual.width,actual.height,{threshold:.1})>actual.width*actual.height*.001)
    throw new Error(`Carrier settings golden changed at ${width}`);
  }
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error(`Overflow at ${width}`);
 }
 await page.setViewportSize({width:1440,height:1000});
 await settings.getByRole('button',{name:'Apply rack replacement',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#operation-status')?.dataset.outcome==='applied');
 await settings.getByRole('combobox',{name:'Installed rack',exact:true}).selectOption('carrier:PREVIEW_T37_38_4R200');
 await page.waitForFunction(()=>document.querySelector('[data-region="carrier-settings"]')?.dataset.currentModel==='RGT_CAR_5R60_A00');
 if(actions.filter(action=>action==='apply').length!==1)throw new Error('Replacement application replayed');
 await page.getByRole('navigation',{name:'Console pages'}).getByRole('link',{name:'Workstation',exact:true}).click();
 await page.getByRole('heading',{name:'Workstation layout',exact:true}).waitFor();
 await page.getByRole('navigation',{name:'Console pages'}).getByRole('link',{name:'System Settings',exact:true}).click();
 await settings.getByRole('combobox',{name:'Installed rack',exact:true}).waitFor();
 if(actions.filter(action=>action==='apply').length!==1 || actions.includes('submit'))throw new Error('Navigation replayed a command');
 if(errors.length)throw new Error(errors.join('\n'));
 console.log(JSON.stringify({applied:true,actions}));
} finally {await browser.close();}

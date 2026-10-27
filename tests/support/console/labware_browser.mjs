import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core'),{PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,output,baselines]=process.argv.slice(2),browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],actions=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST') actions.push(r.postDataJSON()?.action);});
 await page.goto(url+'#station');
 await page.getByRole('button',{name:'Edit labware',exact:true}).click();
 await page.getByLabel('Rack site',{exact:true}).waitFor({timeout:12000}).catch(async error=>{throw new Error(error.message+'\n'+await page.locator('[data-region=labware-editor]').innerText());});
 await page.getByRole('button',{name:'Place labware · PREVIEW_T36_5R60_SUBSTITUTE · site 2',exact:true}).click();
 await page.getByLabel('Labware category',{exact:true}).selectOption('reservoir');
 await page.getByLabel('Labware model',{exact:true}).selectOption('RGT_CONT_60ML_BC_A00');
 await page.getByLabel('Labware identifier',{exact:true}).fill('BrowserVessel');
 await page.getByRole('button',{name:'Check placement',exact:true}).click();
 await page.getByRole('heading',{name:'Checked proposal · not applied',exact:true}).waitFor();
 for(const width of [1440,390]) {
  await page.setViewportSize({width,height:1000});
  const actual=await page.locator('[data-region="labware-editor"]').screenshot({path:output.replace('.png',`-${width}.png`),animations:'disabled'});
  const file=`${baselines}/labware-editor-${width}.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(file,actual);
  else {const ref=PNG.sync.read(readFileSync(file)),img=PNG.sync.read(actual);
   if(ref.width!==img.width || ref.height!==img.height || pixelmatch(ref.data,img.data,null,img.width,img.height,{threshold:.1})>img.width*img.height*.001)
    throw new Error(`Labware golden changed at ${width}`);
  }
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error(`Page overflow at ${width}`);
 }
 await page.setViewportSize({width:1440,height:1000});
 if(actions.includes('apply'))throw new Error('Preview applied without consent');
 await page.getByRole('button',{name:'Apply checked change',exact:true}).click();
 await page.getByRole('button',{name:'Inspect deck item BrowserVessel · carrier PREVIEW_T36_5R60_SUBSTITUTE · site 2',exact:true}).waitFor();
 await page.getByRole('button',{name:'Edit labware',exact:true}).click();
 await page.getByLabel('Rack site',{exact:true}).waitFor({timeout:12000}).catch(async error=>{throw new Error(error.message+'\n'+await page.locator('[data-region=labware-editor]').innerText());});
 await page.getByRole('button',{name:'Inspect deck item BrowserVessel · carrier PREVIEW_T36_5R60_SUBSTITUTE · site 2',exact:true}).click();
 await page.getByRole('button',{name:'Check removal',exact:true}).waitFor();
 await page.getByRole('button',{name:'Check removal',exact:true}).click();
 await page.getByRole('heading',{name:'Checked proposal · not applied',exact:true}).waitFor();
 if(actions.filter(a=>a==='apply').length!==1)throw new Error('Unexpected application count');
 if(actions.includes('submit'))throw new Error('Editing submitted a program');
 if(errors.length)throw new Error(errors.join('\n'));
 console.log(JSON.stringify({applied:true,actions}));
} finally {await browser.close();}

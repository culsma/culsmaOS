import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core'),{PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,output,baselines]=process.argv.slice(2),browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],actions=[],durations=[],started=new WeakMap();
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST') actions.push(r.postDataJSON()?.action);if(r.url().endsWith('/api/v1/configuration/labware'))started.set(r,performance.now());});
 page.on('requestfinished',r=>{if(started.has(r))durations.push(performance.now()-started.get(r));});
 await page.goto(url+'#station');
 const empty=page.getByRole('button',{name:'Place labware · PREVIEW_T36_5R60_SUBSTITUTE · site 2',exact:true});
 await empty.waitFor();
 if(await page.getByRole('button',{name:'Edit labware',exact:true}).count())throw new Error('Separate edit-mode button remains');
 // A failed catalogue read must be visible immediately inside the selected position.
 await page.route('**/api/v1/configuration/labware',async route=>{
  if(route.request().postDataJSON()?.action==='catalogue')return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'TEST_CHOICES_UNAVAILABLE'}})});
  await route.continue();
 });
 await page.setViewportSize({width:900,height:1000});
 const initialScroll=await page.locator('[data-region="workstation-layout"] .setup-deck-scroll').evaluate(node=>{node.scrollLeft=140;return node.scrollLeft;});
 if(initialScroll<10)throw new Error('Direct-edit scroll test did not scroll the deck');
 await empty.click();
 const dialog=page.getByRole('dialog',{name:'Edit rack position',exact:true});await dialog.waitFor();
 await dialog.getByRole('alert').waitFor();
 if(await dialog.getByRole('button',{name:'Apply checked change',exact:true}).count())throw new Error('Failed catalogue left an apply button');
 await page.unroute('**/api/v1/configuration/labware');
 await dialog.getByRole('button',{name:'Retry loading choices',exact:true}).click();
 await dialog.getByLabel('Contents',{exact:true}).waitFor();
 await dialog.getByLabel('Contents',{exact:true}).selectOption('empty');
 if(await dialog.getByRole('button',{name:'Check removal',exact:true}).isEnabled())throw new Error('Already empty position can be removed');
 await page.keyboard.press('Escape');
 await dialog.waitFor({state:'detached'});
 if(!(await empty.evaluate(node=>node===document.activeElement)))throw new Error('Escape lost deck focus');
 if(Math.abs(await page.locator('[data-region="workstation-layout"] .setup-deck-scroll').evaluate(node=>node.scrollLeft)-initialScroll)>1)throw new Error('Closing the dialog reset deck scroll');
 await page.setViewportSize({width:1440,height:1000});
 const scroll=page.locator('[data-region="workstation-layout"] .setup-deck-scroll');
 await empty.click();await dialog.getByLabel('Contents',{exact:true}).waitFor();
 await dialog.getByLabel('Contents',{exact:true}).selectOption('reservoir');
 await dialog.getByLabel('Labware model',{exact:true}).selectOption('RGT_CONT_60ML_BC_A00');
 await dialog.getByText('Advanced identification',{exact:true}).click();
 await dialog.getByLabel('Labware identifier',{exact:true}).fill('BrowserVessel');
 await dialog.getByRole('button',{name:'Check placement',exact:true}).click();
 await dialog.getByRole('heading',{name:'Checked proposal · not applied',exact:true}).waitFor();
 for(const width of [1440,390]) {
  await page.setViewportSize({width,height:1000});
  const actual=await dialog.screenshot({path:output.replace('.png',`-${width}.png`),animations:'disabled'});
  const file=`${baselines}/labware-editor-${width}.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(file,actual);
  else {const ref=PNG.sync.read(readFileSync(file)),img=PNG.sync.read(actual);
   if(ref.width!==img.width || ref.height!==img.height || pixelmatch(ref.data,img.data,null,img.width,img.height,{threshold:.1})>img.width*img.height*.001)
    throw new Error(`Labware dialog golden changed at ${width}`);
  }
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error(`Page overflow at ${width}`);
 }
 await page.setViewportSize({width:1440,height:1000});
 if(actions.includes('apply'))throw new Error('Preview applied without consent');
 await dialog.getByRole('button',{name:'Apply checked change',exact:true}).click();
 const placed=page.getByRole('button',{name:'Inspect deck item BrowserVessel · carrier PREVIEW_T36_5R60_SUBSTITUTE · site 2',exact:true});
 await placed.waitFor();await dialog.waitFor({state:'detached'});
 // Occupied positions use the same direct click, including explicit emptying.
 await placed.click();await dialog.getByLabel('Contents',{exact:true}).waitFor();
 await dialog.getByLabel('Contents',{exact:true}).selectOption('empty');
 await dialog.getByRole('button',{name:'Check removal',exact:true}).click();
 await dialog.getByRole('heading',{name:'Checked proposal · not applied',exact:true}).waitFor();
 await dialog.getByRole('button',{name:'Apply checked change',exact:true}).click();
 await empty.waitFor();await dialog.waitFor({state:'detached'});
 // Existing vendor models, not just newly placed items, can be changed in place.
 await page.getByRole('button',{name:'Inspect deck item HT_L_0003 · carrier CAR_5TIP_0001 · site 2',exact:true}).click();
 await dialog.getByLabel('Contents',{exact:true}).waitFor();
 await dialog.getByLabel('Labware model',{exact:true}).selectOption('ST_L.rck');
 await dialog.getByRole('button',{name:'Check replacement',exact:true}).click();
 await dialog.getByRole('heading',{name:'Checked proposal · not applied',exact:true}).waitFor();
 for(const width of [1440,390]) {
  await page.setViewportSize({width,height:1000});
  const png=await dialog.screenshot({path:output.replace('.png',`-occupied-${width}.png`),animations:'disabled'});
  const file=`${baselines}/occupied-labware-${width}.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(file,png);
  else {const ref=PNG.sync.read(readFileSync(file)),img=PNG.sync.read(png);
   if(ref.width!==img.width || ref.height!==img.height || pixelmatch(ref.data,img.data,null,img.width,img.height,{threshold:.1})>img.width*img.height*.001)
    throw new Error(`Occupied labware golden changed at ${width}`);
  }
 }
 await page.setViewportSize({width:1440,height:1000});
 // Complete replacement, then remove and refill the original occupied site.
 await dialog.getByRole('button',{name:'Apply checked change',exact:true}).click();
 await dialog.waitFor({state:'detached'});
 const original=page.getByRole('button',{name:'Inspect deck item HT_L_0003 · carrier CAR_5TIP_0001 · site 2',exact:true});
 await original.click();await dialog.getByLabel('Contents',{exact:true}).waitFor();
 await dialog.getByLabel('Contents',{exact:true}).selectOption('empty');
 await dialog.getByRole('button',{name:'Check removal',exact:true}).click();
 await dialog.getByRole('button',{name:'Apply checked change',exact:true}).click();
 const cleared=page.getByRole('button',{name:'Place labware · CAR_5TIP_0001 · site 2',exact:true});
 await cleared.waitFor();await dialog.waitFor({state:'detached'});
 await cleared.click();await dialog.getByLabel('Contents',{exact:true}).waitFor();
 await dialog.getByLabel('Contents',{exact:true}).selectOption('tips');
 await dialog.getByLabel('Labware model',{exact:true}).selectOption('HT_L.rck');
 await dialog.getByText('Advanced identification',{exact:true}).click();
 await dialog.getByLabel('Labware identifier',{exact:true}).fill('HT_L_0003');
 await dialog.getByRole('button',{name:'Check placement',exact:true}).click();
 await dialog.getByRole('button',{name:'Apply checked change',exact:true}).click();
 await original.waitFor();await dialog.waitFor({state:'detached'});
 await page.reload();
 try {await original.waitFor({timeout:8000});} catch(error) {
  await page.screenshot({path:output.replace('.png','-reload-failure.png')});
  writeFileSync(output.replace('.png','-reload-failure.txt'),JSON.stringify({errors,visible:await page.locator('body').innerText()}));
  throw error;
 }
 await original.click();await dialog.getByLabel('Contents',{exact:true}).waitFor();
 await dialog.screenshot({path:output.replace('.png','-restored.png'),animations:'disabled'});
 await dialog.getByRole('button',{name:'Close',exact:true}).click();
 await page.getByRole('button',{name:'Inspect deck item DWP96_E4 · carrier CAR_HHS_3DWP_0001 · site 4',exact:true}).click();
 await dialog.getByLabel('Contents',{exact:true}).waitFor();
 await dialog.getByLabel('Contents',{exact:true}).selectOption('reservoir');
 await dialog.getByLabel('Labware model',{exact:true}).selectOption('Nun_100ml_96C_Rgt_L.rck');
 await dialog.getByRole('button',{name:'Check replacement',exact:true}).click();
 await dialog.getByRole('region',{name:'Related configuration changes',exact:true}).getByText(/Clear liquid capacity/).waitFor();
 await dialog.getByRole('button',{name:'Close',exact:true}).click();
 await dialog.waitFor({state:'detached'});
 if(actions.filter(a=>a==='apply').length!==5)throw new Error('Unexpected application count');
 if(actions.includes('submit'))throw new Error('Editing submitted a program');
 if(errors.length)throw new Error(errors.join('\n'));
 if(!durations.length || Math.max(...durations)>3000)throw new Error('Layout edit request exceeded 3 seconds: '+Math.max(...durations));
 console.log(JSON.stringify({applied:true,direct_position_edit:true,remove_refill_persisted:true,max_edit_ms:Math.round(Math.max(...durations)),actions}));
} finally {await browser.close();}

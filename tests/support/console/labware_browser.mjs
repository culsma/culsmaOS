import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core'),{PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,output,baselines]=process.argv.slice(2),browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],actions=[],durations=[],started=new WeakMap();
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST')actions.push(r.postDataJSON()?.action);if(r.url().endsWith('/api/v1/configuration/labware'))started.set(r,performance.now());});
 page.on('requestfinished',r=>{if(started.has(r))durations.push(performance.now()-started.get(r));});
 const dialog=page.getByRole('dialog',{name:'Edit rack position',exact:true}),save=dialog.getByRole('button',{name:'Save changes',exact:true});
 const item=name=>page.getByRole('button',{name,exact:true});
 const empty=item('Place labware · PREVIEW_T36_5R60_SUBSTITUTE · site 2');
 async function open(control){await control.click();await dialog.getByLabel('Contents',{exact:true}).waitFor();}
 async function select(category,model){await dialog.getByLabel('Contents',{exact:true}).selectOption(category);if(model)await dialog.getByLabel('Labware model',{exact:true}).selectOption(model);}
 async function persist(control){await save.click();await dialog.waitFor({state:'detached'});await control.waitFor();}
 async function golden(prefix){
  for(const width of [1440,390]) {
   await page.setViewportSize({width,height:1000});
   const png=await dialog.screenshot({path:output.replace('.png',`-${prefix}-${width}.png`),animations:'disabled'});
   const file=`${baselines}/${prefix==='occupied'?'occupied-labware':'labware-editor'}-${width}.png`;
   if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(file,png);
   else {const ref=PNG.sync.read(readFileSync(file)),img=PNG.sync.read(png);
    if(ref.width!==img.width || ref.height!==img.height || pixelmatch(ref.data,img.data,null,img.width,img.height,{threshold:.1})>img.width*img.height*.001)throw new Error(`Labware golden changed: ${prefix}/${width}`);
   }
   const separation=await dialog.evaluate(node=>{
    const fields=node.querySelector('.labware-fields').getBoundingClientRect(),actions=node.querySelector('.labware-actions').getBoundingClientRect();
    return actions.top-fields.bottom;
   });
   if(separation<20)throw new Error('Save buttons collide with inputs');
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error('Page overflow');
  }
  await page.setViewportSize({width:1440,height:1000});
 }
 await page.goto(url+'#station');await empty.waitFor();
 await page.route('**/api/v1/configuration/labware',async route=>{
  if(route.request().postDataJSON()?.action==='catalogue')return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'TEST_CHOICES_UNAVAILABLE'}})});
  await route.continue();
 });
 await page.setViewportSize({width:900,height:1000});
 const scroll=page.locator('[data-region="workstation-layout"] .setup-deck-scroll');
 const initialScroll=await scroll.evaluate(node=>{node.scrollLeft=140;return node.scrollLeft;});
 await empty.click();await dialog.getByRole('alert').waitFor();
 const selectedScroll=await scroll.evaluate(node=>node.scrollLeft);
 if(await save.count())throw new Error('Failed catalogue left a save button');
 await page.unroute('**/api/v1/configuration/labware');
 await dialog.getByRole('button',{name:'Retry loading choices',exact:true}).click();await dialog.getByLabel('Contents',{exact:true}).waitFor();
 if(await save.isEnabled())throw new Error('Empty position can be saved without changes');
 await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
 if(!(await empty.evaluate(node=>node===document.activeElement)))throw new Error('Escape lost deck focus');
 if(Math.abs(await scroll.evaluate(node=>node.scrollLeft)-selectedScroll)>1)throw new Error('Closing reset deck scroll');
 await page.setViewportSize({width:1440,height:1000});
 await open(empty);await select('reservoir','RGT_CONT_60ML_BC_A00');
 await dialog.getByText('Advanced identification',{exact:true}).click();await dialog.getByLabel('Labware identifier',{exact:true}).fill('BrowserVessel');
 await golden('empty');
 if(actions.includes('prepare') || actions.includes('apply'))throw new Error('Editing alone saved a change');
 // A rejected validation keeps choices, with no apply request; the same Save retries validation.
 await page.route('**/api/v1/configuration/labware',async route=>{
  if(route.request().postDataJSON()?.action==='prepare')return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:{code:'TEST_PLACEMENT_REJECTED'}})});
  await route.continue();
 });
 await save.click();await dialog.getByRole('alert').waitFor();
 if(await dialog.getByLabel('Labware model',{exact:true}).inputValue()!=='RGT_CONT_60ML_BC_A00')throw new Error('Validation lost model choice');
 if(actions.includes('apply'))throw new Error('Rejected validation reached apply');
 await page.unroute('**/api/v1/configuration/labware');
 // Lose an accepted response: reconcile status, never submit the mutation twice.
 let lost=false;
 await page.route('**/api/v1/configuration/activation',async route=>{
  if(route.request().postDataJSON()?.action==='apply' && !lost){lost=true;await route.fetch();return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'TEST_RESPONSE_LOST'}})});}
  await route.continue();
 });
 const placed=item('Inspect deck item BrowserVessel · carrier PREVIEW_T36_5R60_SUBSTITUTE · site 2');
 await persist(placed);await page.unroute('**/api/v1/configuration/activation');
 if(actions.filter(a=>a==='apply').length!==1)throw new Error('Lost response repeated save');
 await open(placed);await select('empty');await persist(empty);
 const original=item('Inspect deck item HT_L_0003 · carrier CAR_5TIP_0001 · site 2');
 await open(original);await select('tips','ST_L.rck');await golden('occupied');
 if(await dialog.getByRole('button',{name:/Check|Apply|Confirm/}).count())throw new Error('Multi-step save controls remain');
 // Keep the dialog until an authoritative terminal receipt, even when the new layout arrives first.
 let held=false;
 await page.route('**/api/v1/configuration/activation',async route=>{
  if(route.request().postDataJSON()?.action==='status' && !held){held=true;const r=await route.fetch(),body=await r.json();body.data.receipt.status='starting';return route.fulfill({response:r,json:body});}
  await route.continue();
 });
 await save.click();await dialog.getByRole('button',{name:'Saving…',exact:true}).waitFor();
 await dialog.waitFor({state:'detached'});await original.waitFor();
 await page.unroute('**/api/v1/configuration/activation');
 await open(original);await select('empty');
 const cleared=item('Place labware · CAR_5TIP_0001 · site 2');await persist(cleared);
 await open(cleared);await select('tips','HT_L.rck');
 await dialog.getByText('Advanced identification',{exact:true}).click();await dialog.getByLabel('Labware identifier',{exact:true}).fill('HT_L_0003');await persist(original);
 await page.reload();await original.waitFor();
 await open(item('Inspect deck item DWP96_E4 · carrier CAR_HHS_3DWP_0001 · site 4'));await select('reservoir','Nun_100ml_96C_Rgt_L.rck');
 await persist(item('Inspect deck item DWP96_E4 · carrier CAR_HHS_3DWP_0001 · site 4'));
 if(!(/Clear liquid capacity/.test(await page.locator('#operation-status').innerText())))throw new Error('Missing cleanup feedback: '+await page.locator('#operation-status').innerText());
 await open(item('Inspect deck item TIP_50ul_L_0001 · carrier CAR_5TIP_0001 · site 1'));await select('empty');
 const firstEmpty=item('Place labware · CAR_5TIP_0001 · site 1');await persist(firstEmpty);
 await page.reload();await firstEmpty.waitFor();
 await page.locator('[data-region=workstation-layout]').screenshot({path:output.replace('.png','-c1-empty.png'),animations:'disabled'});
 if(actions.filter(a=>a==='apply').length!==7)throw new Error('Unexpected save count');
 if(actions.includes('submit'))throw new Error('Editing submitted an experiment');
 if(errors.length)throw new Error(errors.join('\n'));
 if(!durations.length || Math.max(...durations)>3000)throw new Error('Layout edit request exceeded 3 seconds');
 console.log(JSON.stringify({applied:true,single_save:true,remove_refill_persisted:true,max_edit_ms:Math.round(Math.max(...durations)),actions}));
} finally {await browser.close();}

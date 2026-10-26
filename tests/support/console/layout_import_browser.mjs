import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core');
const {PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,nativeFile,generatedFile,output,baselines,unsupportedFile]=process.argv.slice(2);
const browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1280,height:960}}),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.goto(url+'#configuration');
 const advanced=page.getByText('Advanced · configuration presets and JSON',{exact:true});
 if(!await advanced.evaluate(node=>node.parentElement.open)) await advanced.click();
 await page.getByLabel('Installed profile',{exact:true}).selectOption('hamilton-layout');
 await page.getByLabel('Import native instrument layout',{exact:true}).setInputFiles(nativeFile);
 const review=page.locator('[data-region="layout-import-review"]');
 await page.waitForFunction(()=>document.querySelector('[data-region="layout-import-review"]')?.dataset.complete==='true');
 if(!await review.getByRole('button',{name:'Use converted layout as configuration',exact:true}).isEnabled()) throw new Error('Lossless instance conversion was blocked');
 const preview=review.locator('[data-region="import-layout-preview"]');
 if(await preview.getByLabel('Recorded object',{exact:true}).locator('option').count()!==91) throw new Error('Missing recorded objects');
 if(await preview.locator('[data-carrier-id]').count()!==12) throw new Error('Track layout was not restored');
 if(await preview.locator('[data-carrier-id="CAR_HHS_3DWP_0001"]').getAttribute('data-track-start')!=='29') throw new Error('Wrong HHS track');
 if(await preview.locator('[data-carrier-id="CAR_5STACK_0002"]').getByRole('button',{name:/DWP96_G1_000/}).count()!==2) throw new Error('Stacked plates were omitted');
 await preview.getByLabel('Recorded object',{exact:true}).selectOption('DWP96_E4');
 const selected=preview.locator('[data-region="recorded-object-selection"]');
 await selected.getByRole('cell',{name:'691.7, 152.5, 182.7',exact:true}).waitFor();
 await review.getByText('91 layout objects',{exact:true}).click();
 await review.locator('[data-region="layout-import-objects"]').getByRole('cell',{name:'ST_L.rck',exact:true}).first().waitFor();
 await review.getByText('91 layout objects',{exact:true}).click();
 await page.locator('#operation-status').evaluate(node=>{node.style.visibility='hidden';});
 for(const width of [1280,390]) {
  await page.setViewportSize({width,height:960});
  await preview.getByLabel('Recorded object',{exact:true}).selectOption('DWP96_E1');
  await preview.getByLabel('Recorded object',{exact:true}).selectOption('DWP96_E4');
  const actual=await review.screenshot({path:output.replace('.png',`-${width}.png`),animations:'disabled'});
  const baseline=`${baselines}/layout-import-${width}.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1') writeFileSync(baseline,actual);
  else {
   const ref=PNG.sync.read(readFileSync(baseline)),image=PNG.sync.read(actual);
   if(ref.width!==image.width || ref.height!==image.height) throw new Error(`Import review dimensions changed at ${width}`);
   if(pixelmatch(ref.data,image.data,null,image.width,image.height,{threshold:.1})>image.width*image.height*.001)
    throw new Error(`Import review pixels changed at ${width}`);
  }
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error(`Import page overflow at ${width}`);
 }
 await page.setViewportSize({width:1280,height:960});
 await review.getByRole('button',{name:'Use converted layout as configuration',exact:true}).click();
 await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('draft-state')?.textContent.includes('Saved revision 1'));
 await page.getByRole('button',{name:'Check saved changes',exact:true}).click();
 await page.locator('#draft-validation').getByText('valid',{exact:true}).waitFor();
 await page.locator('[data-region="station-settings"]').getByLabel('Recorded object',{exact:true}).selectOption('DWP96_E4');
 await page.locator('#draft-validation').getByText('valid',{exact:true}).waitFor();
 // Read the persisted draft through the UI; importing does not activate the station.
 if(!await advanced.evaluate(node=>node.parentElement.open)) await advanced.click();
 await page.getByText('Advanced configuration JSON',{exact:true}).click();
 const imported=JSON.parse(await page.getByRole('textbox',{name:'Advanced configuration JSON',exact:true}).inputValue());
 if(imported.schema!=='hamilton_layout_instances_v1' || imported.layout.objects.length!==91) throw new Error('Full instance configuration was not saved');
 await page.reload();
 if(!await advanced.evaluate(node=>node.parentElement.open)) await advanced.click();
 await page.getByRole('button',{name:'Load test32_water_plate_heat_deck_r2.lay · r1',exact:true}).click();
 await page.locator('[data-region="station-settings"]').getByLabel('Recorded object',{exact:true}).selectOption('DWP96_CE');
 await page.locator('[data-region="station-settings"]').getByRole('cell',{name:'180°',exact:true}).waitFor();
 // Unsupported references still fail closed; accepting native instances is not a blanket bypass.
 if(!await advanced.evaluate(node=>node.parentElement.open)) await advanced.click();
 await page.getByLabel('Installed profile',{exact:true}).selectOption('hamilton-layout');
 await page.getByLabel('Import native instrument layout',{exact:true}).setInputFiles(unsupportedFile);
 await page.waitForFunction(()=>document.querySelector('[data-region="layout-import-review"]')?.dataset.complete==='false');
 if(await review.getByRole('button',{name:'Use converted layout as configuration',exact:true}).isEnabled()) throw new Error('Unsupported conversion was accepted');
 await page.getByLabel('Import native instrument layout',{exact:true}).setInputFiles(generatedFile);
 await page.waitForFunction(()=>document.querySelector('[data-region="layout-import-review"]')?.dataset.complete==='true');
 await review.getByRole('button',{name:'Use converted layout as configuration',exact:true}).click();
 if(!await advanced.evaluate(node=>node.parentElement.open)) await advanced.click();
 await page.getByText('Advanced configuration JSON',{exact:true}).click();
 const config=JSON.parse(await page.getByRole('textbox',{name:'Advanced configuration JSON',exact:true}).inputValue());
 if(config.schema!=='hamilton_layout_proposal_v1' || config.carriers.plates.track!=='4') throw new Error('Editable proposal roundtrip changed');
 if(errors.length) throw new Error(errors.join('\n'));
 console.log(JSON.stringify({retained_objects:91,incomplete_blocked:true,instance_saved_and_reloaded:true,roundtrip_configuration:config}));
} finally {await browser.close();}

import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core');
const {PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,nativeFile,generatedFile,output,baselines]=process.argv.slice(2);
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
 await page.waitForFunction(()=>document.querySelector('[data-region="layout-import-review"]')?.dataset.complete==='false');
 if(await review.getByRole('button',{name:'Use converted layout as configuration',exact:true}).isEnabled()) throw new Error('Incomplete conversion was accepted');
 const preview=review.locator('[data-region="import-layout-preview"]');
 if(await preview.locator('[data-carrier-id]').count()!==6) throw new Error('Wrong converted carrier count');
 const hhs=preview.locator('[data-carrier-id="CAR_HHS_3DWP_0001"]');
 if(await hhs.getAttribute('data-track-start')!=='29' || await hhs.getAttribute('data-track-span')!=='7') throw new Error('Imported carrier position differs');
 await preview.getByLabel('Preview object',{exact:true}).selectOption('DWP96_E4');
 const selected=preview.locator('[data-region="import-layout-selection"]');
 if(await selected.getAttribute('data-object-id')!=='DWP96_E4') throw new Error('Preview selection was not applied');
 await selected.getByRole('cell',{name:'691.7, 152.5, 182.7',exact:true}).waitFor();
 await selected.getByText('Source placement needs review; the candidate is not a verified reproduction.',{exact:true}).waitFor();
 await review.getByText('91 layout objects',{exact:true}).click();
 await review.locator('[data-region="layout-import-objects"]').getByRole('cell',{name:'ST_L.rck',exact:true}).first().waitFor();
 await review.locator('[data-region="layout-import-objects"]').getByRole('cell',{name:'DWP96_E4',exact:true}).waitFor();
 await review.getByText('91 layout objects',{exact:true}).click();
 await page.locator('#operation-status').evaluate(node=>{node.style.visibility='hidden';});
 for(const width of [1280,390]) {
  await page.setViewportSize({width,height:960});
  await preview.getByLabel('Preview object',{exact:true}).selectOption('DWP96_E1');
  await preview.getByLabel('Preview object',{exact:true}).selectOption('DWP96_E4');
  const inView=await preview.evaluate(node=>{
   const view=node.querySelector('.setup-deck-scroll').getBoundingClientRect();
   const target=node.querySelector('[data-labware-id="DWP96_E4"]').getBoundingClientRect();
   return target.left>=view.left && target.right<=view.right;
  });
  if(!inView) throw new Error(`Selected imported position is outside the visible deck at ${width}`);

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
 await page.getByLabel('Import native instrument layout',{exact:true}).setInputFiles(generatedFile);
 await page.waitForFunction(()=>document.querySelector('[data-region="layout-import-review"]')?.dataset.complete==='true');
 await review.getByRole('button',{name:'Use converted layout as configuration',exact:true}).click();
 if(!await advanced.evaluate(node=>node.parentElement.open)) await advanced.click();
 await page.getByText('Advanced configuration JSON',{exact:true}).click();
 const json=await page.getByRole('textbox',{name:'Advanced configuration JSON',exact:true}).inputValue();
 const config=JSON.parse(json);
 if(config.schema!=='hamilton_layout_proposal_v1' || config.carriers.plates.track!=='4') throw new Error('Imported configuration was not used');
 if(errors.length) throw new Error(errors.join('\n'));
 console.log(JSON.stringify({retained_objects:91,incomplete_blocked:true,roundtrip_configuration:config}));
} finally {await browser.close();}

import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core'),{PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,output,baselines]=process.argv.slice(2),browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1280,height:960}}),errors=[],posts=[];
 page.on('pageerror',error=>errors.push(error.message));page.on('request',r=>{if(r.method()==='POST' && r.postDataJSON()?.action!=='catalogue')posts.push(r.url());});
 await page.goto(url+'#station');
 const layout=page.locator('[data-region="workstation-layout"]');
 await layout.locator('[data-carrier-id="CAR_HHS_3DWP_0001"]').waitFor();
 if(await layout.locator('[data-carrier-id]').count()!==12) throw new Error('Configured deck is incomplete');
 const identity=await layout.getAttribute('data-configuration-fingerprint');
 await layout.getByRole('button',{name:/^Inspect deck item DWP96_E4 /}).click();
 const dialog=page.getByRole('dialog',{name:'Edit rack position',exact:true});
 await dialog.getByText('DWP96_E4',{exact:true}).waitFor();
 await dialog.getByRole('button',{name:'Close',exact:true}).click();
 await dialog.waitFor({state:'detached'});
 for(const width of [1280,390]) {
  await page.setViewportSize({width,height:960});
  const actual=await layout.screenshot({path:`${output}/overview-layout-${width}.png`,animations:'disabled'}),file=`${baselines}/overview-layout-${width}.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1') writeFileSync(file,actual);
  else {const ref=PNG.sync.read(readFileSync(file)),img=PNG.sync.read(actual);
   if(ref.width!==img.width || ref.height!==img.height || pixelmatch(ref.data,img.data,null,img.width,img.height,{threshold:.1})>img.width*img.height*.001)
    throw new Error(`Overview golden changed at ${width}`);
  }
  const viewport=layout.locator('.setup-deck-scroll');
  const narrow=layout.locator('[data-carrier-id="PREVIEW_T36_5R60_SUBSTITUTE"]');
  if((await narrow.boundingBox()).width<70)throw new Error('Narrow carrier is unreadable');
  if(await narrow.locator('.setup-deck-stack-label').count())throw new Error('Narrow carrier repeats site labels');
  const stack=layout.locator('[data-carrier-id="CAR_5STACK_0003"] .setup-deck-stack');
  for(const node of await stack.locator('.setup-deck-site').all())if((await node.boundingBox()).height<24)throw new Error('Stacked item is squeezed');
  await viewport.evaluate(node=>node.scrollLeft=node.scrollWidth);
  const right=await layout.screenshot({path:`${output}/overview-layout-${width}-right.png`,animations:'disabled'}),rightFile=`${baselines}/overview-layout-${width}-right.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(rightFile,right);
  else {const ref=PNG.sync.read(readFileSync(rightFile)),img=PNG.sync.read(right);if(ref.width!==img.width || ref.height!==img.height || pixelmatch(ref.data,img.data,null,img.width,img.height,{threshold:.1})>img.width*img.height*.001)throw new Error(`Right deck golden changed at ${width}`);}
  await viewport.evaluate(node=>node.scrollLeft=0);
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error(`Overflow at ${width}`);
 }
 await page.reload();await layout.locator('[data-carrier-id="CAR_HHS_3DWP_0001"]').waitFor();
 if(await layout.getAttribute('data-configuration-fingerprint')!==identity) throw new Error('Reload changed configuration identity');
 if(posts.length) throw new Error('Overview wrote state: '+posts.join(','));
 if(errors.length) throw new Error(errors.join('\n'));
 console.log(JSON.stringify({carriers:12,automatic_current_layout:true,posts:posts.length}));
} finally {await browser.close();}

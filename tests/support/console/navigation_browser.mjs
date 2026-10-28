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
  const body=request.postDataJSON();if(['submit','start','confirm','begin','revise','apply','save','create','cancel'].includes(body?.action))writes.push(body.action);
 }});
 const ready=()=>page.waitForFunction(()=>document.querySelector('#content')?.dataset.loadState==='ready' && document.querySelector('#content')?.getAttribute('aria-busy')==='false');
 const nav=page.getByRole('navigation',{name:'Console pages'});
 await page.goto(url+'#run/'+runId);
 await page.getByRole('heading',{name:'Load the experiment',exact:true}).waitFor();await ready();
 const fingerprint=await page.locator('#content [data-region="run-setup"]').getAttribute('data-setup-fingerprint');
 if(await page.locator('#content [data-region="workstation-files"]').count())throw new Error('Experiment still contains the file browser');
 const runTitle='Experiment · '+runId.slice(0,8);
 await page.getByRole('button',{name:'Minimize '+runTitle,exact:true}).click();
 await page.waitForURL('**#desktop');
 if(!await page.locator('#desktop-home').isVisible())throw new Error('Minimize did not reveal desktop');
 await page.getByRole('button',{name:'Show '+runTitle,exact:true}).click();
 await page.getByRole('heading',{name:'Load the experiment',exact:true}).waitFor();await ready();
 if(await page.locator('#content [data-region="run-setup"]').getAttribute('data-setup-fingerprint')!==fingerprint)throw new Error('Window restoration changed loading plan');
 await page.getByRole('button',{name:'Close '+runTitle,exact:true}).click();await page.waitForURL('**#desktop');
 if(await page.locator('.console-window').count())throw new Error('Closing view left its frame mounted');
 await nav.getByRole('link',{name:'Files',exact:true}).click();await ready();
 await page.getByRole('complementary',{name:'Program files'}).waitFor();
 if(await page.locator('#content [data-region="workstation-layout"]').count())throw new Error('Files still contains permanent workstation layout');
 await nav.getByRole('link',{name:'Workstation',exact:true}).click();
 await page.getByRole('heading',{name:'Workstation layout',exact:true}).waitFor();await ready();
 if(await page.locator('.console-window').count()!==2)throw new Error('Destinations did not retain separate windows');
 // Keep the declared track scale and scroll through repeated station snapshots.
 await page.setViewportSize({width:900,height:960});
 const scroll=page.locator('#content [data-region="workstation-layout"] .setup-deck-scroll');
 const position=await scroll.evaluate(node=>{node.scrollLeft=140;return node.scrollLeft;});
 if(position<10)throw new Error('Test deck did not scroll');
 for(let i=0;i<2;i++) {
  await page.getByRole('button',{name:'Refresh',exact:true}).click();await ready();
  if(Math.abs(await scroll.evaluate(node=>node.scrollLeft)-position)>1)throw new Error('Refresh reset deck scroll');
 }
 await page.setViewportSize({width:1280,height:960});
 const frame=page.locator('.console-window[data-active="true"]'),before=await frame.boundingBox();
 const title=page.getByRole('button',{name:'Workstation',exact:true});
 const titleBox=await title.boundingBox();
 await page.mouse.move(titleBox.x+50,titleBox.y+12);await page.mouse.down();await page.mouse.move(titleBox.x+90,titleBox.y+42);await page.mouse.up();
 const moved=await frame.boundingBox();if(moved.x<=before.x+20 || moved.y<=before.y+15)throw new Error('Window did not move');
 await page.getByRole('button',{name:'Maximize Workstation',exact:true}).click();
 if(!(await frame.getAttribute('class')).includes('maximized'))throw new Error('Maximize failed');
 await page.getByRole('button',{name:'Restore Workstation',exact:true}).click();
 await nav.getByRole('link',{name:'System Settings',exact:true}).click();
 await page.getByText('Advanced · configuration presets and JSON',{exact:true}).waitFor();await ready();
 await page.getByText('Advanced · configuration presets and JSON',{exact:true}).click();
 await page.getByRole('button',{name:'New from profile',exact:true}).click();
 const input=page.getByRole('textbox',{name:'Configuration name',exact:true});await input.fill('Keep this unsaved edit');
 await page.getByRole('button',{name:'Close System Settings',exact:true}).click();
 await page.getByText('Save or discard the open edit before closing or minimizing this window.',{exact:true}).waitFor();
 await nav.getByRole('link',{name:'System Info',exact:true}).click();
 await page.getByRole('heading',{name:'Configured equipment',exact:true}).waitFor();await ready();
 if(await page.locator('#content input,#content select,#content textarea').count())throw new Error('System Info gained editable fields');
 await nav.getByRole('link',{name:'System Settings',exact:true}).click();await ready();
 if(await page.getByRole('textbox',{name:'Configuration name',exact:true}).inputValue()!=='Keep this unsaved edit')throw new Error('Window switch lost unsaved edit');
 // Leave the unsaved settings in its own background window, then show the desktop.
 await page.getByRole('link',{name:'Show desktop',exact:true}).click();await page.waitForURL('**#desktop');
 await nav.getByRole('link',{name:'Workstation',exact:true}).click();await ready();
 for(const width of [1280,390]) {
  await page.setViewportSize({width,height:960});
  await page.locator('#content .setup-deck-scroll').evaluate(node=>node.scrollLeft=0);
  const actual=await page.screenshot({path:`${output}/desktop-${width}.png`,animations:'disabled',maskColor:'#e8edf3',mask:[page.locator('.status-strip'),page.locator('.program-location'),page.locator('#alert')]});
  const file=`${baselines}/desktop-${width}.png`;
  if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(file,actual);
  else {const ref=PNG.sync.read(readFileSync(file)),image=PNG.sync.read(actual);
   if(ref.width!==image.width || ref.height!==image.height || pixelmatch(ref.data,image.data,null,image.width,image.height,{threshold:.1})>image.width*image.height*.001)
    throw new Error(`Desktop golden changed at ${width}`);
  }
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error(`Overflow at ${width}`);
  if(!await nav.getByRole('link',{name:'Files',exact:true}).isVisible())throw new Error('Taskbar hidden on mobile');
 }
 if(await page.locator('#window-tasks .window-task').count())throw new Error('Fixed applications have duplicate task buttons');
 if(await page.locator('.taskbar-divider').isVisible())throw new Error('Empty experiment task divider is visible');
 if(writes.length)throw new Error('Window lifecycle sent business commands: '+writes.join(', '));
 if(errors.length)throw new Error(errors.join('\n'));
 console.log(JSON.stringify({independent_windows:true,dirty_edit_preserved:true,navigation_writes:0,loading_plan_unchanged:true}));
} finally {await browser.close();}

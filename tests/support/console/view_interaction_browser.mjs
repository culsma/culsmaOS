import {createRequire} from 'node:module';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {readFileSync,writeFileSync} from 'node:fs';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core'),{PNG}=require('pngjs');
const pixelmatch=(await import(`${process.env.CULSMA_OS_BROWSER_MODULES}/pixelmatch/index.js`)).default;
const [url,socket,runId,entity,python,output,baseline]=process.argv.slice(2),run=promisify(execFile);
async function mcp(view,id,requestId) {
 const env={...process.env,PYTHONPATH:process.env.CULSMA_OS_MCP_SDK_PATH+':'+process.cwd()+'/src'};
 const result=await run(python,['-m','tests.support.console.view_mcp_client',socket,view,id,requestId],{env,timeout:30000});
 return JSON.parse(result.stdout.trim());
}
const browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1280,height:1000}}),errors=[],commands=[],failed=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('response',response=>{if(response.status()>=400)failed.push({path:new URL(response.url()).pathname,status:response.status()});});
 page.on('request',request=>{if(request.method()==='POST' && !request.url().includes('/console/'))commands.push(request.postDataJSON()?.action);});
 await page.goto(url+'#station');
 try {await page.getByRole('heading',{name:'Workstation layout',exact:true}).waitFor();}
 catch {throw new Error(JSON.stringify({errors,failed,headings:await page.locator('#content h2').allTextContents(),alert:await page.locator('#alert').textContent()}));}
 let receipt=await mcp('experiment',runId,'view-experiment');
 if(receipt.status!=='displayed')throw new Error(JSON.stringify(receipt));
 await page.locator('#content [data-region="run-outcome"]').waitFor();
 if(!page.url().includes(runId))throw new Error('MCP did not select requested run');
 receipt=await mcp('reveal',entity,'view-reveal');
 if(receipt.status!=='displayed')throw new Error(JSON.stringify({receipt,view:await page.locator('#content').getAttribute('data-page'),entities:await page.locator('[data-action="workstation.inspect-layout-item"]').evaluateAll(nodes=>nodes.map(n=>n.dataset.entityId))}));
 const revealed=page.locator('.console-revealed');await revealed.waitFor();
 if(await revealed.getAttribute('data-entity-id')!==entity)throw new Error('Wrong entity highlighted');
 if(await page.locator('[data-region="labware-editor"]').count())throw new Error('Reveal opened an editor');
 const actual=await page.locator('#content [data-region="workstation-layout"]').screenshot({path:output,animations:'disabled'});
 if(process.env.CULSMA_OS_CAPTURE_GOLDEN==='1')writeFileSync(baseline,actual);
 else {
  const ref=PNG.sync.read(readFileSync(baseline)),image=PNG.sync.read(actual);
  if(ref.width!==image.width || ref.height!==image.height || pixelmatch(ref.data,image.data,null,image.width,image.height,{threshold:.1})>image.width*image.height*.001)
   throw new Error('Reveal golden changed');
 }
 receipt=await mcp('settings','-','view-settings');
 if(receipt.status!=='displayed')throw new Error(JSON.stringify(receipt));
 await page.getByText('Advanced · configuration presets and JSON',{exact:true}).click();
 await page.getByRole('button',{name:'New from profile',exact:true}).click();
 const input=page.getByRole('textbox',{name:'Configuration name',exact:true});await input.waitFor();
 await input.fill((await input.inputValue())+' unsaved');
 receipt=await mcp('experiment',runId,'view-dirty');
 if(receipt.status!=='deferred' || !page.url().endsWith('#configuration'))throw new Error('Unsaved changes were displaced');
 if(!((await input.inputValue()).endsWith(' unsaved')))throw new Error('Unsaved edit lost');
 if(commands.some(action=>['start','submit','apply','confirm','begin','save','create','cancel'].includes(action)))
  throw new Error('Presentation sent a business command: '+commands.join(','));
 if(errors.length)throw new Error(errors.join('\n'));
 await page.close();
 let state;
 for(let i=0;i<3;i++) {state=await mcp('state','-','-');if(!state.sessions.some(row=>row.online))break;await new Promise(r=>setTimeout(r,500));}
 if(state.sessions.some(row=>row.online))throw new Error('Closed renderer remained online');
 console.log(JSON.stringify({mcp_stdio:true,experiment:'displayed',entity:'displayed',dirty_edit:'deferred',business_writes:0,closed:true}));
} finally {await browser.close();}

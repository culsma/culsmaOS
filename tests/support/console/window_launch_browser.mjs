import {createRequire} from 'node:module';
const require=createRequire(`${process.env.CULSMA_OS_BROWSER_MODULES}/package.json`);
const {chromium}=require('playwright-core');
const [url]=process.argv.slice(2),browser=await chromium.launch({executablePath:process.env.CULSMA_OS_CHROME,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1280,height:960}}),errors=[],starts=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(request.method()==='POST' && new URL(request.url()).pathname==='/api/v1/programs' && request.postDataJSON()?.action==='start')starts.push(request.postDataJSON());});
 await page.goto(url);
 const file=page.getByRole('button',{name:'transfer.culs',exact:true});await file.waitFor();await file.dblclick();
 await page.waitForURL('**#run/*');
 await page.locator('#content [data-region="run-outcome"]').getByText('Experiment completed.',{exact:true}).waitFor();
 const hash=new URL(page.url()).hash,runId=decodeURIComponent(hash.slice('#run/'.length)),title='Experiment · '+runId.slice(0,8);
 if(await page.locator('.console-window').count()!==2)throw new Error('Execution did not open its own window');
 if(await page.locator('#content [data-region="workstation-layout"]').count())throw new Error('Result is still buried in the workstation');
 const volume=await page.locator('#content').getByRole('cell',{name:'100',exact:true}).count();
 if(!volume)throw new Error('No material result displayed');
 await page.waitForFunction(()=>document.querySelector('#content')?.getAttribute('aria-busy')==='false');
 await page.getByRole('button',{name:'Close '+title,exact:true}).click();
 await page.waitForURL('**#programs');
 // Reopen the durable run by identity, rather than starting the file again.
 await page.evaluate(hash=>location.hash=hash,hash);
 await page.locator('#content [data-region="run-outcome"]').getByText('Experiment completed.',{exact:true}).waitFor();
 if(starts.length!==1)throw new Error('Presentation restarted the experiment');
 if(errors.length)throw new Error(errors.join('\n'));
 console.log(JSON.stringify({run_id:runId,start_requests:starts.length}));
} finally {await browser.close();}

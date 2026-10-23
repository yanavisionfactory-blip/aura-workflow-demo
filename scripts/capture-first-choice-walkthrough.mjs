// Build-time rendering of the isolated public demo. This process never opens
// a user session, reads private runs or permits non-local network requests.
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { chromium } from 'playwright';
import { tour } from '../src/showcase/first-choice-seo/scenario.mjs';
const root=path.resolve('dist');
const frames=path.resolve('.first-choice-frames');
await fs.mkdir(frames,{recursive:true});
const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.ico':'image/x-icon'};
const server=http.createServer(async(req,res)=>{
 try{let pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);if(pathname.endsWith('/'))pathname+='index.html';const file=path.resolve(root,'.'+pathname);if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}const bytes=await fs.readFile(file);res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream'});res.end(bytes);}catch{res.writeHead(404).end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const port=server.address().port;
const channel=process.env.AURA_BROWSER_CHANNEL;
if(channel && channel!=='chrome')throw new Error('Only the preinstalled Chrome channel is supported');
const browser=await chromium.launch({headless:true,...(channel?{channel}:{})});
try{
 const context=await browser.newContext({viewport:{width:1440,height:990},deviceScaleFactor:1,reducedMotion:'reduce'});
 await context.route('**/*',route=>new URL(route.request().url()).origin===`http://127.0.0.1:${port}`?route.continue():route.abort());
 const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 for(let i=0;i<tour.length;i++){
  await page.goto(`http://127.0.0.1:${port}/showcase/first-choice-seo/?scene=${i}`,{waitUntil:'networkidle'});
  await page.locator('[aria-label="Guided walkthrough"]').waitFor();
  if(tour[i].phase==='execution')await page.waitForTimeout(5000);
  else await page.waitForTimeout(650);
  await page.screenshot({path:path.join(frames,`scene-${String(i).padStart(2,'0')}.jpg`),type:'jpeg',quality:90});
  console.log(`${i+1}/${tour.length}: ${tour[i].title}`);
 }
 // Verify the interactive controls against the local static build only.
 await page.goto('http://127.0.0.1:'+port+'/showcase/first-choice-seo/?screen=review',{waitUntil:'networkidle'});
 await page.getByRole('button',{name:'Ask AURA',exact:true}).click();
 await page.getByLabel('Editing instruction').fill('Make it shorter and clearer');
 await page.getByRole('button',{name:'Generate simulated revision',exact:true}).click();
 await page.getByText('After · proposed revision',{exact:true}).waitFor();
 await page.getByRole('dialog').getByRole('button',{name:'Edit manually',exact:true}).click();
 await page.getByLabel('Article title',{exact:true}).fill('AC Repair Dallas: Review Before Publication');
 await page.getByRole('button',{name:'Save demo draft',exact:true}).click();
 await page.getByRole('dialog').waitFor({state:'hidden'});
 await page.goto('http://127.0.0.1:'+port+'/showcase/first-choice-seo/?screen=results',{waitUntil:'networkidle'});
 await page.locator('[aria-label="Primary WordPress output"]').getByRole('heading',{name:'AC Repair Dallas: Review Before Publication',exact:true}).waitFor();
 const secondary=page.locator('[aria-label="Other tool outputs"] details');
 if(await secondary.count()!==4)throw new Error('Expected four secondary tool dropdowns');
 for(const detail of await secondary.all())if(await detail.getAttribute('open')!==null)throw new Error('Secondary outputs must start closed');
 await secondary.nth(1).locator('summary').click();
 await secondary.nth(1).getByText('AC Repair Dallas: Review Before Publication',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Restore original demo copy',exact:true}).click();
 await page.locator('[aria-label="Primary WordPress output"]').getByRole('heading',{name:"AC Repair in Dallas: Make Your First Service Conversation Count",exact:true}).waitFor();
 await page.setViewportSize({width:390,height:844});
 await page.goto('http://127.0.0.1:'+port+'/showcase/first-choice-seo/?screen=results',{waitUntil:'networkidle'});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+2);
 if(overflow)throw new Error('Mobile results overflow the viewport');
 await page.screenshot({path:path.join(frames,'mobile-results.jpg'),type:'jpeg',quality:90,fullPage:true});
 console.log('Local editor, persistence, secondary outputs, restore and mobile width checks passed');
 if(errors.length)throw new Error(`Demo render errors: ${errors.join('; ')}`);
 await context.close();
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}

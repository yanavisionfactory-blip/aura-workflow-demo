// Build-time rendering of the isolated public demo. This process never opens
// a user session, reads private runs or permits non-local network requests.
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { chromium } from 'playwright';
import { tour } from '../src/showcase/website-content/scenario.mjs';
const root=path.resolve('dist');
const frames=path.resolve('.walkthrough-frames');
await fs.mkdir(frames,{recursive:true});
const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.ico':'image/x-icon'};
const server=http.createServer(async(req,res)=>{
 try{let pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);if(pathname.endsWith('/'))pathname+='index.html';const file=path.resolve(root,'.'+pathname);if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}const bytes=await fs.readFile(file);res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream'});res.end(bytes);}catch{res.writeHead(404).end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const port=server.address().port;
const browser=await chromium.launch({headless:true});
try{
 const context=await browser.newContext({viewport:{width:1440,height:990},deviceScaleFactor:1,reducedMotion:'reduce'});
 await context.route('**/*',route=>new URL(route.request().url()).origin===`http://127.0.0.1:${port}`?route.continue():route.abort());
 const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 for(let i=0;i<tour.length;i++){
  await page.goto(`http://127.0.0.1:${port}/showcase/website-content/?scene=${i}`,{waitUntil:'networkidle'});
  await page.locator('[aria-label="Guided walkthrough"]').waitFor();
  if(tour[i].phase==='execution')await page.waitForTimeout(5000);
  else await page.waitForTimeout(650);
  await page.screenshot({path:path.join(frames,`scene-${String(i).padStart(2,'0')}.jpg`),type:'jpeg',quality:90});
  console.log(`${i+1}/${tour.length}: ${tour[i].title}`);
 }
 if(errors.length)throw new Error(`Demo render errors: ${errors.join('; ')}`);
 await context.close();
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}

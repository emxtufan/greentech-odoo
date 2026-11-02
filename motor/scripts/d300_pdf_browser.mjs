import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('C:/Users/GPRO/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root=process.cwd(), work=path.join(root,'logs/d300-20261020');
const creds=JSON.parse(await fs.readFile(path.join(root,'config/acces-financiar-test.json'),'utf8'));
const saved=JSON.parse(await fs.readFile(path.join(work,'browser-live.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
 headless:true,args:['--disable-gpu','--disable-background-networking']});
const page=await browser.newPage({viewport:{width:1800,height:1200}}), errors=[];
page.on('pageerror',e=>errors.push(e.message));
async function record(){
 const out=await page.evaluate(async id=>fetch('/web/dataset/call_kw/gt.anaf.d300/read',{
  method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',
   params:{model:'gt.anaf.d300',method:'read',args:[[id]],kwargs:{fields:['state','duk_log','xsd_log','validated_hash','pdf_file'],
    context:{allowed_company_ids:[1],lang:'ro_RO'}}}})}).then(r=>r.json()),saved.id);
 if(out.error)throw Error(out.error.data.message);
 return out.result[0];
}
try{
 await page.goto('http://127.0.0.1:8070/web/login');
 const auth=await page.evaluate(async params=>fetch('/web/session/authenticate',{
  method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({jsonrpc:'2.0',method:'call',params})}).then(r=>r.json()),
  {db:creds.database,login:creds.login,password:creds.password});
 assert(auth.result?.uid);
 await page.goto(saved.link);
 await page.locator('.gt-d300-cards').waitFor();
 const before=await record();assert.equal(before.state,'pdf');assert.equal(before.duk_log.trim(),'ok');
 let pending=page.waitForEvent('download');
 await page.getByRole('button',{name:'Descarcă XML',exact:true}).click();
 let dl=await pending;
 assert(!dl.suggestedFilename().includes('NEVALIDAT'));
 await dl.saveAs(path.join(root,'output/pdf/D300_DEMO_2026_10.xml'));
 const after=await record();
 assert.equal(after.state,'pdf');assert.equal(after.validated_hash,before.validated_hash);assert.equal(after.pdf_file,before.pdf_file);
 await page.getByRole('button',{name:'Validează ANAF',exact:true}).click();
 for(let i=0;i<120;i++){
  const r=await record();
  if(r.state==='valid')break;
  await new Promise(resolve=>setTimeout(resolve,500));
 }
 assert.equal((await record()).state,'valid');
 pending=page.waitForEvent('download',{timeout:120000});
 await page.getByRole('button',{name:'Descarcă PDF ANAF',exact:true}).click();
 dl=await pending;
 await dl.saveAs(path.join(root,'output/pdf/D300_DEMO_2026_10.pdf'));
 const final=await record();assert.equal(final.state,'pdf');assert.equal(final.duk_log.trim(),'ok');
 assert(final.xsd_log.includes('DUK'));
 await page.getByRole('tab',{name:'Validări și fișiere'}).click();
 await page.screenshot({path:path.join(work,'anaf-browser-final.png'),fullPage:true});
 assert.deepEqual(errors,[]);
 await fs.writeFile(path.join(work,'browser-anaf.json'),JSON.stringify({
  status:'passed',id:saved.id,action:saved.action,duk:'ok',state:final.state,
  xml_download_preserves_validation:true,pdf_download:true,page_errors:errors,
  validated_hash:final.validated_hash},null,2));
 console.log('D300_ANAF_BROWSER_OK');
}finally{await browser.close();}

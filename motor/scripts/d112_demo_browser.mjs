import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('C:/Users/GPRO/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root=process.cwd(),work=path.join(root,'logs/d112-demo-20261020');
const target=process.argv.includes('--live')?'live':'test';
const validated=process.argv.includes('--validated');
const base=`http://127.0.0.1:${target==='live'?8070:8072}`;
const creds=JSON.parse(await fs.readFile(path.join(root,'config/acces-financiar-test.json'),'utf8'));
const state=JSON.parse(await fs.readFile(path.join(work,'state.json'),'utf8'));
const demo=JSON.parse(await fs.readFile(path.join(work,`${target}-demo.json`),'utf8'));
const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
 headless:true,args:['--disable-gpu','--disable-background-networking']});
const context=await browser.newContext({viewport:{width:1600,height:1100}});
const page=await context.newPage(),errors=[];
page.on('pageerror',e=>errors.push(e.message));
async function rpc(model,method,args=[],kwargs={}){
 const out=await page.evaluate(async data=>fetch(`/web/dataset/call_kw/${data.model}/${data.method}`,{
 method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({jsonrpc:'2.0',method:'call',params:data})}).then(r=>r.json()),
 {model,method,args,kwargs:{...kwargs,context:{allowed_company_ids:[demo.company_id],lang:'ro_RO'}}});
 if(out.error)throw Error(out.error.data?.message||out.error.message);
 return out.result;
}
try{
 await page.goto(base+'/web/login');
 const auth=await page.evaluate(async params=>fetch('/web/session/authenticate',{
 method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({jsonrpc:'2.0',method:'call',params})}).then(r=>r.json()),
 {db:target==='live'?creds.database:state.database,login:creds.login,password:creds.password});
 assert(auth.result?.uid);
 const period=(await rpc('gt.ro.payroll.period','read',[[demo.period_id]],{fields:['state','gross','net','cam','line_ids','company_id']}))[0];
 assert.equal(period.state,'generated');assert.equal(period.net,19315);
 assert.equal(period.gross,33000);assert.equal(period.cam,743);assert.equal(period.line_ids.length,3);
 assert.equal(period.company_id[0],demo.company_id);
 await page.goto(`${base}/odoo/action-730/${demo.period_id}`);
 await page.locator('.o_form_view').waitFor();
 await page.getByText('Ion Popescu [DEMO]',{exact:true}).waitFor();
 await page.getByText('Mara Ionescu [DEMO]',{exact:true}).waitFor();
 await page.getByText('Radu Dumitrescu [DEMO]',{exact:true}).waitFor();
 await page.waitForTimeout(300);
 await page.screenshot({path:path.join(work,`${target}-demo-payroll.png`)});
 const dec=(await rpc('gt.anaf.d112','read',[[demo.declaration_id]],{
 fields:['state','duk_log','schema_log','validated_hash','payload','filing_note']}))[0];
 if(validated){
   assert.equal(dec.state,'pdf');assert(dec.validated_hash);assert.equal(dec.duk_log.trim(),'ok');
 }else{
   assert.equal(dec.state,'invalid');assert(!dec.validated_hash);assert.match(dec.duk_log,/Java/);
 }
 assert.match(dec.filing_note,/DATE FICTIVE/);
 assert.equal(dec.payload.children.filter(n=>n.tag==='asigurat').length,3);
 await page.goto(`${base}/odoo/action-728/${demo.declaration_id}`);
 await page.locator('.gt-d112-fields').first().waitFor();
 await page.getByRole('tab',{name:'Validări',exact:true}).click();
 if(validated)await page.locator('.o_field_widget[name=duk_log]').getByText('ok',{exact:true}).waitFor();
 else await page.getByText('Java nu este instalat',{exact:false}).first().waitFor();
 await page.waitForTimeout(300);
 await page.screenshot({path:path.join(work,`${target}-demo-validation.png`)});
 await page.getByRole('tab',{name:'Fișiere',exact:true}).click();
 const pending=page.waitForEvent('download');
 await page.locator('.o_field_widget[name=work_xml] a').first().click();
 const download=await pending;
 assert.match(download.suggestedFilename(),/LUCRU_NEVALIDAT/);
 const downloaded=path.join(work,`${target}-browser.xml`);
 await download.saveAs(downloaded);
 assert.equal(await fs.readFile(downloaded,'utf8'),await fs.readFile(path.join(work,`${target}-demo.xml`),'utf8'));
 if(validated){
   const pendingXml=page.waitForEvent('download');
   await page.locator('.o_field_widget[name=xml_output] a').first().click();
   const xml=await pendingXml;
   const xmlPath=path.join(root,'logs/d112-java-20261020/browser-validated.xml');
   await xml.saveAs(xmlPath);
   assert.equal(await fs.readFile(xmlPath,'utf8'),await fs.readFile(downloaded,'utf8'));
   const pendingPdf=page.waitForEvent('download');
   await page.locator('.o_field_widget[name=pdf_output] a').first().click();
   const pdf=await pendingPdf;
   const pdfPath=path.join(root,'logs/d112-java-20261020/browser-demo.pdf');
   await pdf.saveAs(pdfPath);
   assert((await fs.readFile(pdfPath)).equals(await fs.readFile(path.join(root,'output/pdf/D112_DEMO_2026_09.pdf'))));
   await page.screenshot({path:path.join(root,'logs/d112-java-20261020/live-downloads.png')});
 }
 assert.deepEqual(errors,[]);
 await fs.writeFile(path.join(work,`browser-${target}.json`),JSON.stringify({
 status:'passed',company:demo.company,period_id:demo.period_id,declaration_id:demo.declaration_id,
 employees:3,net:period.net,xml_download:true,java_missing_reported:!validated,pdf_download:validated,page_errors:errors
 },null,2));
 console.log('D112_DEMO_BROWSER_OK',target);
}finally{await browser.close();}

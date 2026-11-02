import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('C:/Users/GPRO/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root=process.cwd(),work=path.join(root,'logs/vat-journals-20261020');
const live=process.argv.includes('--live'),target=live?'live':'test';
const creds=JSON.parse(await fs.readFile(path.join(root,'config/acces-financiar-test.json'),'utf8'));
const state=JSON.parse(await fs.readFile(path.join(work,'state.json'),'utf8'));
const fixture=JSON.parse(await fs.readFile(path.join(work,'fixture.json'),'utf8'));
const base=`http://127.0.0.1:${live?8070:8072}`;
const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
 headless:true,args:['--disable-gpu','--disable-background-networking']});
const context=await browser.newContext({viewport:{width:1800,height:1200}});
const page=await context.newPage(),errors=[];
page.on('pageerror',e=>errors.push(e.message));
async function rpc(model,method,args=[],kwargs={}){
 const out=await page.evaluate(async data=>fetch(`/web/dataset/call_kw/${data.model}/${data.method}`,{
 method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({jsonrpc:'2.0',method:'call',params:data})}).then(r=>r.json()),
 {model,method,args,kwargs:{...kwargs,context:{allowed_company_ids:[1],lang:'ro_RO'}}});
 if(out.error)throw Error(out.error.data?.message||out.error.message);
 return out.result;
}
const results={status:'passed',target,reports:{},page_errors:errors};
try{
 await page.goto(base+'/web/login');
 const auth=await page.evaluate(async params=>fetch('/web/session/authenticate',{
 method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({jsonrpc:'2.0',method:'call',params})}).then(r=>r.json()),
 {db:live?creds.database:state.database,login:creds.login,password:creds.password});
 assert(auth.result?.uid);
 const actions=await rpc('ir.model.data','search_read',[[['module','=','greentech_ro_vat_journals'],['name','in',['purchase_action','sale_action']]]],
 {fields:['name','res_id']});
 for(const kind of ['purchase','sale']){
  const action=actions.find(a=>a.name===`${kind}_action`).res_id;
  let id=fixture.reports[kind];
  if(live){
   [id]=await rpc('gt.ro.vat.journal','create',[[{company_id:1,kind,date_from:'2026-10-01',date_to:'2026-10-31'}]]);
  }
  await page.goto(`${base}/odoo/action-${action}/${id}`);
  await page.locator('.gt-vat-journal').waitFor();
  await page.getByRole('button',{name:'Actualizează jurnalul',exact:true}).click();
  await page.locator('.gt-vat-summary').waitFor();
  const [record]=await rpc('gt.ro.vat.journal','read',[[id]],{fields:['data']});
  if(!live){
   assert.equal(record.data.totals.base,3000);assert.equal(record.data.totals.eligible,420);
   assert.equal(record.data.totals.pending_vat,210);
   assert.equal(record.data.warnings.length,0);
   await page.locator('.gt-vat-summary tbody tr').filter({hasText:'TVA la plată/încasare'}).click();
   await page.waitForFunction(()=>document.querySelectorAll('.gt-vat-documents tbody tr').length===1);
   assert.equal(await page.locator('.gt-vat-documents tbody tr').count(),1);
   await page.locator('.gt-vat-documents tbody tr').first().click();
   await page.locator('.gt-vat-payments tbody tr').waitFor();
   assert.equal(await page.locator('.gt-vat-payments tbody tr').count(),1);
   await page.locator('.gt-total').click();
  }
  await page.screenshot({path:path.join(work,`${target}-${kind}.png`),fullPage:true});
  for(const [label,ext] of [['Export Excel (CSV)','csv'],['Descarcă PDF','pdf']]){
   const pending=page.waitForEvent('download',{timeout:60000});
   await page.getByRole('button',{name:label,exact:true}).click();
   const download=await pending;
   const output=path.join(work,`${target}-${kind}.${ext}`);
   await download.saveAs(output);
   const bytes=await fs.readFile(output);
   if(ext==='pdf')assert.equal(bytes.subarray(0,5).toString(),'%PDF-');
   else assert(bytes.toString('utf8').includes('TOTAL'));
  }
  if(!live){
   await page.locator('.gt-vat-documents tbody tr').first().getByRole('button',{name:'Deschide'}).click();
   await page.locator('.o_form_view .o_field_widget[name=move_type]').waitFor({state:'attached'});
   assert((await page.locator('.o_form_view').innerText()).includes('TEST UI JURNALE TVA'));
  }
  results.reports[kind]={action,id,rows:record.data.rows.length,warnings:record.data.warnings.length,totals:record.data.totals};
  if(live){
   await page.goto(`${base}/odoo/action-${action}`);
   await page.locator('.gt-vat-journal').waitFor();
   await page.getByRole('button',{name:'Actualizează jurnalul',exact:true}).click();
   await page.locator('.gt-vat-summary').waitFor();
   results.reports[kind].fresh_menu_flow=true;
  }
 }
 assert.deepEqual(errors,[]);
 await fs.writeFile(path.join(work,`browser-${target}.json`),JSON.stringify(results,null,2));
 console.log('VAT_JOURNALS_BROWSER_OK',target);
}catch(e){
 await page.screenshot({path:path.join(work,`${target}-failure.png`)});
 await fs.writeFile(path.join(work,`${target}-failure.txt`),(await page.locator('body').innerText())+'\n'+errors.join('\n'));
 throw e;
}finally{await browser.close();}

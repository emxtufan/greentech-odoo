import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('C:/Users/GPRO/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root=process.cwd(), work=path.join(root,'logs/d300-20261020');
const live=process.argv.includes('--live'), target=live?'live':'test', port=live?8070:8072;
const creds=JSON.parse(await fs.readFile(path.join(root,'config/acces-financiar-test.json'),'utf8'));
const state=JSON.parse(await fs.readFile(path.join(work,'state.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
 headless:true,args:['--disable-gpu','--disable-background-networking']});
const page=await browser.newPage({viewport:{width:1800,height:1200}}), errors=[];
page.on('pageerror',e=>errors.push(e.message));
async function rpc(model,method,args=[],kwargs={}){
 const out=await page.evaluate(async data=>fetch(`/web/dataset/call_kw/${data.model}/${data.method}`,{
 method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({jsonrpc:'2.0',method:'call',params:data})}).then(r=>r.json()),
 {model,method,args,kwargs:{...kwargs,context:{allowed_company_ids:[1],lang:'ro_RO'}}});
 if(out.error)throw Error(out.error.data?.message||out.error.message);
 return out.result;
}
try{
 await page.goto(`http://127.0.0.1:${port}/web/login`);
 const auth=await page.evaluate(async params=>fetch('/web/session/authenticate',{
 method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({jsonrpc:'2.0',method:'call',params})}).then(r=>r.json()),
 {db:live?creds.database:state.database,login:creds.login,password:creds.password});
 assert(auth.result?.uid);
 const [company]=await rpc('res.company','read',[[1]],{fields:['name','l10n_ro_caen_code']});
 assert.equal(company.name,'GreenTech Financiar DEMO - date fictive');
 await rpc('ir.config_parameter','set_param',['gt_d300.duk_dir',path.join(root,'tools/anaf/d300')]);
 const [id]=await rpc('gt.anaf.d300','create',[[{
  company_id:1,year:2026,month:10,period_type:'L',vat_registered:true,balances_reviewed:true,special_reviewed:true,
  signer_last:'TEST',signer_first:'DEMO',signer_role:'Administrator DEMO',caen:company.l10n_ro_caen_code||'4321',
  bank_name:'BANCA DEMO',bank_account:'RO49AAAA1B31007593840000',
 }]]);
 await rpc('gt.anaf.d300','action_standard_mappings',[[id]]);
 const [act]=await rpc('ir.model.data','search_read',[[['module','=','greentech_anaf_d300'],['name','=','declaration_action']]],
  {fields:['res_id']});
 const action=act.res_id;
 await page.goto(`http://127.0.0.1:${port}/odoo/action-${action}/${id}`);
 await page.locator('.gt-d300').waitFor();
 await page.getByRole('button',{name:'Actualizează din contabilitate',exact:true}).click();
 await page.locator('.gt-d300-cards').waitFor();
 const [record]=await rpc('gt.anaf.d300','read',[[id]],{fields:['data','state']});
 assert.deepEqual(record.data.errors,[],JSON.stringify(record.data.errors));
 assert.equal(record.state,'calculated');
 const rows=Object.fromEntries(record.data.rows.map(r=>[r.code,r]));
 assert.equal(rows['19'].tax,4568);
 assert.equal(rows['31'].tax,3429);
 assert.equal(rows['44'].tax,1139);
 await page.locator('.gt-d300-rows tbody tr').filter({hasText:'Livrări și servicii 21%'}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.gt-d300-sources tbody tr').length===11);
 await page.screenshot({path:path.join(work,`${target}-decont.png`),fullPage:true});
 for(const [label,ext] of [['Descarcă XML','xml'],['Export situație CSV','csv']]){
  const pending=page.waitForEvent('download');
  await page.getByRole('button',{name:label,exact:true}).click();
  const dl=await pending;const output=path.join(work,`${target}-d300.${ext}`);
  await dl.saveAs(output);
  const text=await fs.readFile(output,'utf8');
  assert(text.includes(ext==='xml'?'R41_2="1139"':'SITUAȚIE DE LUCRU'));
 }
 await page.getByRole('button',{name:'Validează ANAF',exact:true}).click();
 await page.waitForTimeout(1200);
 const [validated]=await rpc('gt.anaf.d300','read',[[id]],{fields:['state','duk_log','validated_at']});
 assert(['xml','valid','warnings','invalid'].includes(validated.state),validated.state);
 if(validated.state==='xml'){
  assert(validated.duk_log.includes('nu este instalat'));
  assert.equal(validated.validated_at,false);
 }
 await page.getByRole('tab',{name:'Validări și fișiere'}).click();
 await page.screenshot({path:path.join(work,`${target}-validari.png`),fullPage:true});
 await page.getByRole('tab',{name:'Decont și documente'}).click();
 await page.locator('.gt-d300-sources tbody tr').first().getByRole('button',{name:'Deschide'}).click();
 await page.locator('.o_form_view .o_field_widget[name=move_type]').waitFor({state:'attached'});
 await page.goto(`http://127.0.0.1:${port}/odoo/action-${action}`);
 await page.getByRole('button',{name:/Nou|New/,exact:true}).first().click();
 await page.locator('.gt-d300').waitFor();
 assert.deepEqual(errors,[]);
 const result={status:'passed',target,action,id,rows:record.data.rows.length,documents:record.data.contributions.length,
  vat_collected:rows['19'].tax,vat_deducted:rows['31'].tax,vat_payable:rows['44'].tax,
  anaf_state:validated.state,page_errors:errors,link:`http://127.0.0.1:${port}/odoo/action-${action}/${id}`};
 await fs.writeFile(path.join(work,`browser-${target}.json`),JSON.stringify(result,null,2));
 console.log('D300_BROWSER_OK',target,JSON.stringify(result));
}catch(e){
 await page.screenshot({path:path.join(work,`${target}-failure.png`),fullPage:true});
 await fs.writeFile(path.join(work,`${target}-failure.txt`),(await page.locator('body').innerText())+'\n'+errors.join('\n'));
 throw e;
}finally{await browser.close();}

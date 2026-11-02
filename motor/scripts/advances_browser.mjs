import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('C:/Users/GPRO/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root=process.cwd(),work=path.join(root,'logs/advances-20261020');
const live=process.argv.includes('--live'), target=live?'live':'test';
const credentials=JSON.parse(await fs.readFile(path.join(root,'config/acces-financiar-test.json'),'utf8'));
const state=JSON.parse(await fs.readFile(path.join(work,'state.json'),'utf8'));
const fixture=JSON.parse(await fs.readFile(path.join(work,'fixture.json'),'utf8'));
const base=`http://127.0.0.1:${live?8070:8072}`;
const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
 headless:true,args:['--disable-gpu','--disable-background-networking']});
const context=await browser.newContext({viewport:{width:1800,height:1200}});
const page=await context.newPage(),errors=[];
page.on('pageerror',e=>errors.push(e.message));
async function rpc(model,method,args=[],kwargs={}){
 const response=await page.evaluate(async params=>fetch(`/web/dataset/call_kw/${params.model}/${params.method}`,{
  method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({jsonrpc:'2.0',method:'call',params})}).then(r=>r.json()),
  {model,method,args,kwargs:{...kwargs,context:{allowed_company_ids:[1],lang:'ro_RO',...kwargs.context}}});
 if(response.error)throw Error(response.error.data?.message||response.error.message);
 return response.result;
}
const result={status:'passed',target,cases:{},page_errors:errors};
try{
 await page.goto(base+'/web/login');
 const auth=await page.evaluate(async params=>fetch('/web/session/authenticate',{
  method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({jsonrpc:'2.0',method:'call',params})}).then(r=>r.json()),
  {db:live?credentials.database:state.database,login:credentials.login,password:credentials.password});
 assert(auth.result?.uid);
 const records=await rpc('ir.model.data','search_read',[[['module','=','greentech_ro_advances'],['model','=','ir.actions.act_window']]],
  {fields:['name','res_id']});
 const actions=Object.fromEntries(records.map(r=>[r.name,r.res_id]));
 result.actions=actions;
 for(const kind of ['sale','purchase']){
  const test=fixture.cases[kind];
  if(!live){
   await page.goto(`${base}/odoo/action-${actions[`create_${kind}_action`]}/${test.create}`);
   const createdResponse=page.waitForResponse(r=>r.url().includes('/call_button/gt.advance.create/action_create'));
   await page.getByRole('button',{name:'Creează factura de avans',exact:true}).click();
   assert(!(await (await createdResponse).json()).error);
   await page.locator('.o_form_view .o_field_widget[name=move_type]').waitFor({state:'attached'});
   const [wizard]=await rpc('gt.advance.create','read',[[test.create]],{fields:['created_move_id']});
   const advance=wizard.created_move_id[0];
   const [before]=await rpc('account.move','read',[[advance]],{fields:['state','amount_residual']});
   if(before.state==='draft')await rpc('account.move','action_post',[[advance]]);
   const [source]=await rpc('account.move.line','search_read',[[['move_id','=',advance],['display_type','=','product']]],
    {fields:['id','name']});
   // Exercise native payment registration and its accounting entry.
   const journals=await rpc('account.journal','search_read',[[['company_id','=',1],['type','=','bank']]],
     {fields:['id','name'],limit:1});
   if(before.amount_residual>0){
    const [pay]=await rpc('account.payment.register','create',[[{
      payment_date:'2026-09-12',amount:1210,journal_id:journals[0].id,
    }]],{context:{active_model:'account.move',active_ids:[advance]}});
    await rpc('account.payment.register','action_create_payments',[[pay]]);
   }
   const [paid]=await rpc('account.move','read',[[advance]],{fields:['amount_residual','payment_state']});
   assert.equal(paid.amount_residual,0);
   const existing=await rpc('account.move.line','search_read',[[['move_id','=',test.final],['gt_advance_origin_id','!=',false]]],{fields:['id']});
   if(!existing.length){
   const [finalState]=await rpc('account.move','read',[[test.final]],{fields:['state']});
   if(finalState.state==='posted')await rpc('account.move','button_draft',[[test.final]]);
   await page.goto(`${base}/odoo/action-${actions[`${kind}_action`]}/${test.final}`);
   await page.getByRole('button',{name:'Regularizează avans',exact:true}).click();
   const dialog=page.locator('.o_dialog');
   const input=dialog.locator('.o_field_widget[name=source_id] input');
   await input.click();
   await page.locator('.o-autocomplete--dropdown-item').filter({hasText:'Avans servicii demonstrative'}).first().click();
   await dialog.locator('.o_field_widget[name=amount] input').fill('400');
   const appliedResponse=page.waitForResponse(r=>r.url().includes('/call_button/gt.advance.allocate/action_apply'));
   await dialog.getByRole('button',{name:'Adaugă regularizarea',exact:true}).click();
   const applied=await (await appliedResponse).json();
   assert(!applied.error,JSON.stringify(applied.error));
   }
   const [finalState2]=await rpc('account.move','read',[[test.final]],{fields:['state']});
   if(finalState2.state==='draft')
   await rpc('account.move','action_post',[[test.final]]);
   const [a]=await rpc('account.move','read',[[advance]],{fields:['gt_advance_used','gt_advance_remaining','amount_residual']});
   assert.equal(a.gt_advance_used,400);assert.equal(a.gt_advance_remaining,600);
   // Ledger/journals must see 1000 + 2500 - 400, not an extra payment turnover.
   const [journal]=await rpc('gt.ro.vat.journal','create',[[{company_id:1,kind,
     partner_id:fixture.partner,date_from:'2026-09-01',date_to:'2026-09-30'}]]);
   await rpc('gt.ro.vat.journal','action_refresh',[[journal]]);
   const [j]=await rpc('gt.ro.vat.journal','read',[[journal]],{fields:['data']});
   assert.equal(j.data.totals.base,3100);assert.equal(j.data.totals.vat,651);
   result.cases[kind]={advance,final:test.final,used:400,remaining:600,paid_residual:paid.amount_residual};
  }
  let report=test.report;
  if(live){
   [report]=await rpc('gt.advance.report','create',[[{company_id:1,kind,
    date_from:'2026-10-01',date_to:'2026-10-31'}]]);
  }
  await page.goto(`${base}/odoo/action-${actions.report_action}/${report}`);
  const reportResponse=page.waitForResponse(r=>r.url().includes('/call_button/gt.advance.report/action_refresh'));
  await page.getByRole('button',{name:'Actualizează situația',exact:true}).click();
  assert(!(await (await reportResponse).json()).error);
  await page.locator('.o_field_widget[name=display_html] table').first().waitFor();
  const [r]=await rpc('gt.advance.report','read',[[report]],{fields:['data']});
  if(!live)assert.equal(r.data.totals.closing,600);
  await page.screenshot({path:path.join(work,`${target}-${kind}.png`),fullPage:true});
  for(const [label,ext] of [['Descarcă PDF','pdf'],['Export Excel (CSV)','csv']]){
   const pending=page.waitForEvent('download');
   await page.getByRole('button',{name:label,exact:true}).click();
   const download=await pending;await download.saveAs(path.join(work,`${target}-${kind}.${ext}`));
  }
  result.cases[kind]={...result.cases[kind],report,report_totals:r.data.totals};
  await page.goto(`${base}/odoo/action-${actions[`${kind}_action`]}`);
  await page.locator('.o_list_view').waitFor();
  assert((await page.locator('body').innerText()).includes('Disponibil fără TVA'));
  if(live){
   await page.goto(`${base}/odoo/action-${actions[`create_${kind}_action`]}`);
   await page.getByRole('button',{name:'Creează factura de avans',exact:true}).waitFor();
   assert((await page.locator('body').innerText()).includes('Se creează o factură în ciornă'));
  }
 }
 assert.deepEqual(errors,[]);
 await fs.writeFile(path.join(work,`browser-${target}.json`),JSON.stringify(result,null,2));
 console.log('ADVANCES_BROWSER_PASSED',target);
}catch(e){
 await page.screenshot({path:path.join(work,`${target}-failure.png`),fullPage:true});
 await fs.writeFile(path.join(work,`${target}-failure.txt`),(await page.locator('body').innerText())+'\n'+errors.join('\n'));
 throw e;
}finally{await browser.close();}

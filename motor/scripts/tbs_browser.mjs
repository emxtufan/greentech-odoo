import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('C:/Users/GPRO/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root=process.cwd(),work=path.join(root,'logs/tbs-modules-20261020');
const live=process.argv.includes('--live'),target=live?'live':'test',base=`http://127.0.0.1:${live?8070:8072}`;
const credentials=JSON.parse(await fs.readFile('config/acces-financiar-test.json','utf8'));
const state=JSON.parse(await fs.readFile(path.join(work,'state.json'),'utf8'));
const fixture=JSON.parse(await fs.readFile(path.join(work,'fixture.json'),'utf8'));
const company=live?1:fixture.company;
const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
 headless:true,args:['--disable-gpu','--disable-background-networking']});
const context=await browser.newContext({viewport:{width:1600,height:1100},acceptDownloads:true});
const page=await context.newPage(),errors=[],report={status:'passed',target,checks:[],page_errors:errors};
page.on('pageerror',e=>errors.push(e.message));
async function rpc(model,method,args=[],kwargs={}){
 const response=await page.evaluate(async params=>fetch(`/web/dataset/call_kw/${params.model}/${params.method}`,{
  method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params})
 }).then(r=>r.json()),{model,method,args,kwargs:{...kwargs,context:{allowed_company_ids:[company],lang:'ro_RO',...kwargs.context}}});
 if(response.error)throw Error(response.error.data?.message||response.error.message);
 return response.result;
}
async function button(method,label){
 const response=page.waitForResponse(r=>r.url().includes(`/call_button/l10n.ro.d406.export.wizard/${method}`));
 await page.getByRole('button',{name:label,exact:true}).click();
 const result=await (await response).json();
 assert(!result.error,JSON.stringify(result.error));
 await page.waitForTimeout(250);
}
try{
 await page.goto(base+'/web/login');
 const auth=await page.evaluate(async params=>fetch('/web/session/authenticate',{
  method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params})
 }).then(r=>r.json()),{db:live?credentials.database:state.database,login:credentials.login,password:credentials.password});
 assert(auth.result?.uid);
 await context.addCookies([{name:'cids',value:String(company),url:base}]);
 const [action]=await rpc('ir.model.data','search_read',[[['module','=','tbs_saft_d406'],['name','=','action_d406_export_wizard']]],{fields:['res_id']});
 report.action=action.res_id;
 let wizard=fixture.wizard;
 if(live){
  [wizard]=await rpc('l10n.ro.d406.export.wizard','create',[[{company_id:1,date_from:'2026-10-01',date_to:'2026-10-31'}]]);
 }
 await page.goto(`${base}/odoo/action-${action.res_id}/${wizard}`);
 await page.getByRole('button',{name:'Verifică datele',exact:true}).waitFor();
 await button('action_check','Verifică datele');
 report.checks.push('D406 form and preflight');
 if(!live){
  await button('action_generate','Generează XML');
  await button('action_validate_duk','Validează cu DUK');
  let [result]=await rpc('l10n.ro.d406.export.wizard','read',[[wizard]],{fields:['xsd_valid','gt_duk_valid','validation_log','gt_xml_sha256']});
  assert(result.xsd_valid && result.gt_duk_valid,JSON.stringify(result));
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'Descarcă XML pentru verificare',exact:true}).click();
  const xmlDownload=await download;
  const xmlPath=path.join(work,'browser-download.xml');await xmlDownload.saveAs(xmlPath);
  assert.equal(crypto.createHash('sha256').update(await fs.readFile(xmlPath)).digest('hex'),result.gt_xml_sha256);
  await button('action_generate_pdf','Generează PDF ANAF');
  const pdfEvent=page.waitForEvent('download');
  await page.getByRole('button',{name:'Descarcă PDF',exact:true}).click();
  await (await pdfEvent).saveAs(path.join(work,'browser-download.pdf'));
  assert((await fs.readFile(path.join(work,'browser-download.pdf'))).subarray(0,5).equals(Buffer.from('%PDF-')));
  report.checks.push('XML generate + XSD + actual ANAF Java validation + XML download + PDF generate/download');
 }
 await page.screenshot({path:path.join(work,`d406-${target}.png`),fullPage:true});
 // Render each installed e-Transport screen without contacting ANAF.
 for(const model of ['stock.picking','stock.picking.batch','l10n.ro.edi.stock.action.wizard',
  'l10n.ro.edi.stock.list.wizard','l10n.ro.edi.stock.transporter.info.wizard','product.template']){
  await rpc(model,'get_views',[],{views:[[false,'form']],options:{toolbar:true}});
 }
 report.checks.push('6 transport/product form architectures');
 const menus=await rpc('ir.model.data','search_read',[[['module','=','greentech_tbs_integration'],['model','=','ir.ui.menu']]],{fields:['name','res_id']});
 assert(menus.length>=3);report.menus=menus;
 const [taxAction]=await rpc('ir.model.data','search_read',[[['module','=','greentech_tbs_integration'],['name','=','action_tax_mapping']]],{fields:['res_id']});
 await page.goto(`${base}/odoo/action-${taxAction.res_id}`);
 await page.locator('.o_list_view').waitFor();
 await page.screenshot({path:path.join(work,`taxes-${target}.png`),fullPage:true});
 report.checks.push('SAF-T tax configuration screen');
 const [transfer]=await rpc('ir.model.data','search_read',[[['module','=','stock'],['name','=','action_picking_tree_all']]],{fields:['res_id']});
 await page.goto(`${base}/odoo/action-${transfer.res_id}`);
 await page.locator('.o_list_view').waitFor();
 await page.screenshot({path:path.join(work,`etransport-${target}.png`),fullPage:true});
 report.checks.push('Transfer list');
 assert.equal(errors.length,0,errors.join('\n'));
}catch(error){report.status='failed';report.error=error.stack;throw error;}
finally{
 await fs.writeFile(path.join(work,`browser-${target}.json`),JSON.stringify(report,null,2));
 await browser.close();
}
console.log(JSON.stringify(report));

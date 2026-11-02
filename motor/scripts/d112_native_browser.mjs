// Native payroll UI flow. Synthetic employees/amounts exist only in the clone.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require('C:/Users/GPRO/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root = process.cwd(), work = path.join(root, 'logs/d112-native-20261020');
const live = process.argv.includes('--live');
const base = `http://127.0.0.1:${live ? 8070 : 8072}`;
const creds = JSON.parse(await fs.readFile(path.join(root, 'config/acces-financiar-test.json'),'utf8'));
const state = JSON.parse(await fs.readFile(path.join(work,'state.json'),'utf8'));
const database = live ? creds.database : state.database;
assert(database.startsWith(live ? 'greentech_financiar_test' : 'gt_d112_'));
const browser = await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
 headless:true,args:['--disable-gpu','--disable-background-networking']});
const context = await browser.newContext({viewport:{width:1600,height:1100}});
const page = await context.newPage(), errors=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('console',e=>{if(e.type()==='error')errors.push(e.text());});
async function rpc(model,method,args=[],kwargs={}){
 const out=await page.evaluate(async ({model,method,args,kwargs})=>fetch(`/web/dataset/call_kw/${model}/${method}`,{
  method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{model,method,args,kwargs}})}).then(r=>r.json()),
  {model,method,args,kwargs});
 if(out.error)throw new Error(out.error.data?.message || out.error.message);
 return out.result;
}
async function fill(name,value){
 const locator=page.locator(`.o_field_widget[name="${name}"] input`).first();
 await locator.fill(value);await locator.press('Tab');
}
async function shot(name){await page.screenshot({path:path.join(work,name)});}
try {
 await page.goto(base+'/web/login');
 const auth=await page.evaluate(async ({db,login,password})=>fetch('/web/session/authenticate',{
  method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{db,login,password}})}).then(r=>r.json()),
  {db:database,login:creds.login,password:creds.password});
 assert(auth.result?.uid);
 if(!live){
  const fixture=(await rpc('res.company','search_read',[[['name','=','TEST INTERFATA SALARII NATIVE']]],{fields:['id']}))[0];
  assert(fixture,'Isolated fixture company absent');
  const old=await rpc('gt.ro.payroll.period','search_read',[[['company_id','=',fixture.id]]],{fields:['id','state']});
  for(const record of old){
   if(record.state!=='draft')await rpc('gt.ro.payroll.period','action_reset',[[record.id]]);
   const docs=await rpc('gt.anaf.d112','search',[[['payroll_period_id','=',record.id]]]);
   if(docs.length)await rpc('gt.anaf.d112','unlink',[docs]);
   await rpc('gt.ro.payroll.period','unlink',[[record.id]]);
  }
 }
 const action=(await rpc('ir.actions.act_window','search_read',[[['res_model','=','gt.ro.payroll.period']]],{fields:['id']}))[0].id;
 await page.goto(`${base}/odoo/action-${action}?debug=assets`);
 await page.locator('.o_list_view,.o_nocontent_help').first().waitFor();
 await shot(live?'native-live-list.png':'native-list.png');
 if(!live){
  await page.locator('.o_list_button_add').click();
  await page.locator('.o_form_view').waitFor();
  await fill('year','2026');
  await page.locator('.o_field_widget[name=month] input').fill('09');
  await page.locator('.o_field_selection_menu').getByText('09',{exact:true}).click();
  await fill('caen','6201');
  await page.locator('.o_field_widget[name=house] input').fill('_B');
  await page.locator('.o_field_selection_menu').getByText('_B',{exact:true}).click();
  await fill('signer_last','TEST');
  await fill('signer_first','INTERFATA');
  await fill('signer_position','ADMINISTRATOR');
  await page.locator('.o_field_widget[name=scope_confirmed] input').check();
  await page.getByRole('button',{name:'Preia angajați și contracte',exact:true}).click();
  await page.getByText('TEST INTERFATA ANGAJAT',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Calculează salariile',exact:true}).click();
  await page.getByRole('tab',{name:'Verificări',exact:true}).click();
  await page.getByText('Confirmați pontajul',{exact:false}).waitFor();
  await shot('native-missing-data.png');
  await page.getByRole('tab',{name:'Salariați și pontaj',exact:true}).click();
  await page.locator('td[name=worked_days]').click();
  const days=page.locator('td[name=worked_days] input');await days.fill('22');await days.press('Tab');
  await page.locator('td[name=confirmed] input').check();
  await page.getByRole('button',{name:'Calculează salariile',exact:true}).click();
  await page.getByRole('button',{name:'Generează D112',exact:true}).waitFor();
  await shot('native-calculated.png');
  const records=await rpc('gt.ro.payroll.period','search_read',[[]],{fields:['state','gross','net','cam','company_id'],order:'id desc',limit:1});
  assert.equal(records[0].state,'calculated');
  assert.equal(records[0].gross,8000);assert.equal(records[0].net,4680);assert.equal(records[0].cam,180);
  await page.getByRole('button',{name:'Generează D112',exact:true}).click();
  await page.locator('.gt-d112-fields').first().waitFor();
  await page.getByRole('button',{name:'Validează ANAF',exact:true}).click();
  await page.getByRole('tab',{name:'Validări',exact:true}).click();
  await page.getByText('Java nu este instalat',{exact:false}).first().waitFor();
  const dec=(await rpc('gt.anaf.d112','search_read',[[['payroll_period_id','=',records[0].id]]],{fields:['payload','state','duk_log','schema_log','validated_hash']}))[0];
  assert.equal(dec.state,'invalid');assert(!dec.validated_hash);
  assert.match(dec.duk_log,/Java/);assert.match(dec.schema_log,/A_sal1/);
  await page.waitForTimeout(250);
  await shot('native-d112-validation.png');
  const insured=dec.payload.children.find(n=>n.tag==='asigurat');
  assert.equal(insured.children[0].attrs.A_sal1,'8000');
  assert.equal(insured.children.find(n=>n.tag==='asiguratE3').attrs.E3_16,'4680');
  await page.getByRole('tab',{name:'Fișiere',exact:true}).click();
  const downloadPromise=page.waitForEvent('download');
  await page.locator('.o_field_widget[name=work_xml] a').first().click();
  const download=await downloadPromise;
  assert.match(download.suggestedFilename(),/NEVALIDAT/);
  await download.saveAs(path.join(work,'TEST-NATIVE-NEVALIDAT.xml'));
  assert.match(await fs.readFile(path.join(work,'TEST-NATIVE-NEVALIDAT.xml'),'utf8'),/A_sal1="8000"/);
  await shot('native-d112-files.png');
 }
 assert.deepEqual(errors,[]);
 await fs.writeFile(path.join(work,live?'browser-live.json':'browser-test.json'),JSON.stringify({
  status:'passed',database,live,action,errors,at:new Date().toISOString(),
  scope:live?'Read-only native payroll menu and list':'Native form, missing-input guard, payroll calculation, D112 mapping, original XSD errors, real missing-Java result, draft XML download'
 },null,2));
 console.log(live?'NATIVE_BROWSER_LIVE_OK':'NATIVE_BROWSER_TEST_OK');
}catch(error){
 await shot(live?'native-live-failure.png':'native-failure.png').catch(()=>{});
 await fs.writeFile(path.join(work,'browser-failure.txt'),String(error)+'\n'+await page.locator('body').innerText().catch(()=>''));
 throw error;
}finally{await browser.close();}

// Headless browser test: synthetic edits occur only in the isolated database.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/GPRO/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root = process.cwd();
const work = path.join(root, 'logs/d112-install-20261020');
const live = process.argv.includes('--live');
const base = `http://127.0.0.1:${live ? 8070 : 8072}`;
const credentials = JSON.parse(await fs.readFile(path.join(root, 'config/acces-financiar-test.json'), 'utf8'));
const state = JSON.parse(await fs.readFile(path.join(work, 'state.json'), 'utf8'));
const database = live ? credentials.database : state.database;
assert(database.startsWith(live ? 'greentech_financiar_test' : 'gt_d112_'));
const browser = await chromium.launch({executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true, args: ['--disable-gpu','--disable-background-networking']});
const context = await browser.newContext({viewport:{width:1440,height:1100}});
const page = await context.newPage();
const errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', e => {if(e.type()==='error')errors.push(e.text());});
async function rpc(model, method, args=[], kwargs={}) {
 const r = await page.evaluate(async ({model,method,args,kwargs}) => fetch(`/web/dataset/call_kw/${model}/${method}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{model,method,args,kwargs}})}).then(r=>r.json()),{model,method,args,kwargs});
 if(r.error)throw new Error(r.error.data?.message || r.error.message);
 return r.result;
}
async function shot(name){await page.screenshot({path:path.join(work,name),fullPage:false});}
try {
 for(let attempt=0;attempt<30;attempt++){
  try{if((await fetch(base+'/web/login')).ok)break;}catch{}
  await new Promise(resolve=>setTimeout(resolve,500));
 }
 await page.goto(base+'/web/login');
 const auth = await page.evaluate(async ({database,login,password})=>fetch('/web/session/authenticate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{db:database,login,password}})}).then(r=>r.json()),{database,login:credentials.login,password:credentials.password});
 assert(auth.result?.uid,'Authentication failed');
 const menus=await rpc('ir.ui.menu','search_read',[[['name','=','ANAF']]],{fields:['name','id']});
 assert(menus.length,'ANAF menu absent');
 const actions=await rpc('ir.actions.act_window','search_read',[[['res_model','=','gt.anaf.d112']]],{fields:['id']});
 const action=actions[0].id;
 await page.goto(`${base}/odoo/action-${action}?debug=assets`);
 await page.locator('.o_list_view,.o_nocontent_help').first().waitFor();
 await shot(live?'anaf-live-list.png':'anaf-test-list.png');
 if(!live){
  await page.route('**/web/dataset/call_kw/gt.anaf.d112/onchange',async route=>{
   await new Promise(resolve=>setTimeout(resolve,120));await route.continue();
  });
  await page.locator('.o_list_button_add').click();
  await page.locator('.o_form_view').waitFor();
  await page.getByRole('button',{name:'Preia date firmă',exact:true}).click();
  await page.locator('.gt-d112-fields').first().waitFor();
  await shot('anaf-test-employer.png');
  await page.getByRole('button',{name:'Asigurați',exact:true}).click();
  await page.getByRole('button',{name:'Adaugă asigurat',exact:true}).click();
  for(const [name,value] of [['CNP / NIF asigurat','1990101010011'],['Nume','TEST'],['Prenume','INTERFATA']]){
   const field=page.getByRole('textbox',{name,exact:true});await field.fill(value);await field.press('Tab');
  }
  await shot('anaf-test-person.png');
  for(const name of ['B.1. Contracte','B.4. Totaluri','C. Alte categorii de asigurați']){
   await page.getByRole('button',{name,exact:true}).click();
  }
  await page.getByRole('button',{name:'Verifică structură',exact:true}).click();
  await page.getByRole('tab',{name:'Validări',exact:true}).click();
  await page.getByText('Java nu este instalat',{exact:false}).waitFor();
  await shot('anaf-test-validation.png');
  assert.equal(await page.getByRole('button',{name:'Generează PDF ANAF',exact:true}).count(),0);
  const records=await rpc('gt.anaf.d112','search_read',[[]],{fields:['payload','state'],order:'id desc',limit:1});
  assert.equal(records[0].state,'invalid');
  const person=records[0].payload.children.find(n=>n.tag==='asigurat');
  assert.equal(person.attrs.numeAsig,'TEST');
  assert.equal(person.attrs.prenAsig,'INTERFATA');
  assert.equal(person.attrs.cnpAsig,'1990101010011');
  assert.deepEqual(person.children.map(n=>n.tag),['asiguratB1','asiguratB4','asiguratC','asiguratE3']);
  await page.reload();await page.locator('.o_form_view').waitFor();
  const settings=await rpc('ir.actions.act_window','search_read',[[['name','=','Configurare ANAF']]],{fields:['id']});
  await page.goto(`${base}/odoo/action-${settings[0].id}?debug=assets`);
  await page.getByText('Declarația 112 — validator local',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Verifică disponibilitatea',exact:true}).click();
  await page.getByText('Java nu este instalat',{exact:false}).waitFor();
  await shot('anaf-test-settings.png');
 }
 const relevant=errors.filter(e=>!e.includes('favicon.ico')&&!e.includes('net::ERR_ABORTED'));
 assert.deepEqual(relevant,[],'Browser errors');
 await fs.writeFile(path.join(work,live?'browser-live.json':'browser-test.json'),JSON.stringify({status:'passed',database,menu:menus[0].id,action,errors:relevant,tested:live?['authentication','menu','list','assets']:['authentication','menu','form','editor','add insured','save','XSD errors','missing Java','reload','settings']},null,2));
 console.log('D112_BROWSER_PASSED',live?'live':'isolated copy');
}catch(e){
 await shot('browser-failure.png').catch(()=>{});
 await fs.writeFile(path.join(work,'browser-failure.txt'),await page.locator('body').innerText().catch(()=>''));
 console.error(e.message,JSON.stringify(errors));process.exitCode=1;
}finally{await browser.close();}

"""Final local HTTP and deploy-payload checks; no extra company imports."""
import ast
import base64
import hashlib
import io
import json
import re
from pathlib import Path
import zipfile
from financial_client import Client

ROOT=Path(__file__).resolve().parents[1]
client=Client()
local=json.loads((ROOT/'logs/saga-migration/local-import-result.json').read_text(encoding='utf-8'))
company=local['company_id']
context={'allowed_company_ids':[company]}
checks=[]
assert client.read('saga.import.batch',local['batch_id'],['state'])['state']=='done'
for model,count in [('saga.document',111),('saga.asset.history',10),('saga.payroll.history',18),('saga.source.row',4778)]:
    assert client.call(model,'search_count',[[('company_id','=',company)]],context=context)==count
checks.append('local_company_counts')
for model in ['saga.import.batch','saga.document','saga.asset.history','saga.payroll.history','saga.source.row']:
    result=client.call(model,'get_views',[[(False,'list'),(False,'form')]],context=context)
    assert result['views']['form']['arch']
checks.append('http_views_all_import_screens')
assert client.call('account.move','search_count',[[('company_id','=',company),('saga_batch_id','=',local['batch_id'])]],context=context)==453
assert client.call('account.move','search_count',[[('company_id','=',1)]],context={'allowed_company_ids':[1]})==79
checks.append('453_imported_and_79_original_demo_moves')
assert client.call('account.move','search_count',[[('company_id','=',company),('saga_batch_id','=',local['batch_id']),('line_ids.account_id.account_type','=','asset_cash')]],context=context)>0
checks.append('cash_bank_menu_domain')
for target, expected in [('customers',4),('vendors',17),('sales',56),('purchases',32),('banks',3),('ledger',None),('partners',None),('statements',0),('employees',1)]:
    jump=client.call('saga.import.batch','action_open_work',[[local['batch_id']]],context=dict(context,saga_screen=target))
    assert jump['params']['company_id']==company
    action=client.read('ir.actions.act_window',jump['params']['action_id'],['res_model','view_mode','views','domain','context'])
    domain=ast.literal_eval(action['domain'].replace('allowed_company_ids[0]',str(company)))
    action_context=ast.literal_eval(action['context'].replace('allowed_company_ids[0]',str(company)))
    count=client.call(action['res_model'],'search_count',[domain],context=context)
    assert expected is None or count==expected,(target,count)
    views=client.call(action['res_model'],'get_views',[action['views']],context=dict(context,**action_context))
    assert views['views']['form']['arch']
checks.append('nine_native_work_screens_company_context_and_counts')
page=client.session.get(client.base+'/odoo/action-512',timeout=30)
page.raise_for_status()
scripts=re.findall(r'<script[^>]+src="([^"]+)"',page.text)
bundles=[client.session.get(client.base+url,timeout=60) for url in scripts if 'web.assets_web' in url]
assert bundles and all(r.status_code==200 for r in bundles)
assert any('greentech_saga_open_company' in r.text for r in bundles)
checks.append('compiled_browser_assets_include_company_switch_action')
manifest=json.loads((ROOT/'logs/saga-deploy/manifest.json').read_text())
installer=Path(manifest['path'])
assert hashlib.sha256(installer.read_bytes()).hexdigest()==manifest['sha256']
tree=ast.parse(installer.read_text(encoding='utf-8'))
constants={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ['PAYLOAD_B64','PAYLOAD_SHA256']}
payload=base64.b64decode(constants['PAYLOAD_B64'])
assert hashlib.sha256(payload).hexdigest()==constants['PAYLOAD_SHA256']
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    assert archive.testzip() is None
    for name in archive.namelist():
        if name=='reader-smoke.fdb':
            expected=ROOT/'deploy/financiar/saga-reader-smoke.fdb'
        else:
            expected=ROOT/'custom_addons'/name
        assert expected.read_bytes()==archive.read(name),name
checks.append('self_contained_server_payload_matches_current_source')
source=json.loads((ROOT/'logs/saga-migration/source-manifest.json').read_text(encoding='utf-8-sig'))
assert hashlib.sha256(Path(source['source']).read_bytes()).hexdigest().upper()==source['sha256']
checks.append('original_saga_backup_unchanged')
report={'passed':len(checks),'checks':checks,'local_url':'http://127.0.0.1:8070/odoo/action-'+str(local['action_id']),
        'browser_visual_check':False,'linux_execution_verified':False,'server_updated':False}
(ROOT/'logs/saga-migration/final-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))

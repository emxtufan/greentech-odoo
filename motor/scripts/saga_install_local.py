"""Install the reusable addon and import the confirmed backup through Odoo RPC."""
import base64
import hashlib
import json
from pathlib import Path
from financial_client import Client

ROOT = Path(__file__).resolve().parents[1]
client = Client()
client.call('ir.module.module','update_list')
module = client.search('ir.module.module',[('name','=','greentech_saga_import')],['id','state'])
assert len(module)==1
if module[0]['state']!='installed':
    client.call('ir.module.module','button_immediate_install',[[module[0]['id']]])
print('SAGA_MODULE_INSTALLED_ON_8070',flush=True)
raw = Path(r'C:\Users\GPRO\Downloads\cont_baza.fdb').read_bytes()
digest = hashlib.sha256(raw).hexdigest()
assert digest.upper()==json.loads((ROOT/'logs/saga-migration/source-manifest.json').read_text(encoding='utf-8-sig'))['sha256']
before = client.search('account.move',[('company_id','=',1)],['id','name','state','amount_total','amount_residual'])
existing = client.search('saga.import.batch',[('source_hash','=',digest),('state','=','done')],['id','state','company_id'])
if existing:
    batch_id=existing[0]['id']
else:
    created=client.call('saga.import.batch','create',[[{'name':'DARIUSMED S.R.L.','expected_cui':'22465902',
        'registry_number':'J40/17918/2007','euid':'ROONRC.J40/17918/2007','city':'București, Sector 6',
        'street':'Str. 1 Mai, Nr. 18, Bl. 17S14, Sc. 1, Et. P, Ap. 12','source_confirmed':True,
        'filename':'cont_baza.fdb','source_file':base64.b64encode(raw).decode()}]])
    batch_id=created[0] if isinstance(created,list) else created
    client.call('saga.import.batch','action_analyze',[[batch_id]])
    batch=client.read('saga.import.batch',batch_id,['state','report'])
    assert batch['state']=='ready',batch['report']
    print('SAGA_HTTP_UPLOAD_ANALYSIS_OK',flush=True)
    client.call('saga.import.batch','action_import',[[batch_id]])
batch=client.read('saga.import.batch',batch_id,['state','report','result_json','company_id'])
assert batch['state']=='done',batch['report']
after=client.search('account.move',[('company_id','=',1)],['id','name','state','amount_total','amount_residual'])
assert before==after,'GreenTech DEMO changed'
result={'batch_id':batch_id,'company_id':batch['company_id'][0],'result':batch['result_json'],
        'demo_unchanged':True,'http_upload_analyze_import_verified':True,
        'action_id':client.ref('greentech_saga_import.action_batches')}
(ROOT/'logs/saga-migration/local-import-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('SAGA_HTTP_IMPORT_OK',json.dumps({k:result[k] for k in ['batch_id','company_id','demo_unchanged','action_id']}))

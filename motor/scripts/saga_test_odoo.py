"""Executed by odoo-bin shell in the isolated SAGA verification database."""
import base64
from collections import Counter
import json
from pathlib import Path

assert env.cr.dbname.startswith('gt_saga_verify_')
root = Path.cwd()
base = root/'logs/saga-migration'
before = env['account.move'].search([('company_id','=',1)])
before_data = before.read(['name','state','amount_total','amount_residual'])
user = env.ref('base.user_admin')
app = env(user=user.id)
batch = app['saga.import.batch'].create({'name':'DARIUSMED S.R.L.','expected_cui':'22465902',
    'registry_number':'J40/17918/2007','euid':'ROONRC.J40/17918/2007','city':'București, Sector 6',
    'street':'Str. 1 Mai, Nr. 18, Bl. 17S14, Sc. 1, Et. P, Ap. 12','source_confirmed':True,
    'filename':'cont_baza.fdb','source_file':base64.b64encode(Path(r'C:\Users\GPRO\Downloads\cont_baza.fdb').read_bytes())})
batch.action_analyze()
assert batch.state=='ready',batch.report
print('SAGA_UPLOAD_ANALYSIS_OK',flush=True)
batch.action_import()
(base/'test-import-result.json').write_text(json.dumps({'state':batch.state,'report':batch.report,'result':batch.result_json},ensure_ascii=False,indent=2),encoding='utf-8')
assert batch.state=='done',batch.report
print('SAGA_IMPORT_OK',json.dumps(batch.result_json,ensure_ascii=True),flush=True)
company = batch.company_id
assert company.vat.replace('RO','')=='22465902'
scope = app(context=dict(app.context,allowed_company_ids=[company.id]))
assert scope['saga.document'].search_count([('company_id','=',company.id)])==111
assert scope['account.move'].search_count([('saga_batch_id','=',batch.id)])==453
assert scope['account.move'].search_count([('saga_batch_id','=',batch.id),('move_type','in',['in_invoice','out_invoice'])])==88
assert scope['saga.source.row'].search_count([('batch_id','=',batch.id)])==4778
assert scope['saga.asset.history'].search_count([('batch_id','=',batch.id)])==10
assert scope['saga.payroll.history'].search_count([('batch_id','=',batch.id)])==18
assert scope['hr.employee'].search_count([('company_id','=',company.id)])==1
for model in ['saga.import.batch','saga.document','saga.asset.history','saga.payroll.history','saga.source.row']:
    result=scope[model].get_views([(False,'list'),(False,'form')])
    assert result['views']['form']['arch'],model
batch.action_import()
assert scope['account.move'].search_count([('saga_batch_id','=',batch.id)])==453
after_data = before.read(['name','state','amount_total','amount_residual'])
assert before_data==after_data,'Existing demo moves changed'
print('SAGA_IDEMPOTENCY_VIEWS_DEMO_PRESERVED_OK',flush=True)
env.cr.commit()

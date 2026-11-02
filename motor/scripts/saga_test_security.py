"""Run in the committed verification DB; all changes rolled back."""
import base64
import json
from pathlib import Path
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.addons.greentech_saga_import.core import normalized_ledger

assert env.cr.dbname.startswith('gt_saga_verify_')
base=Path.cwd()/'logs/saga-migration'
checks=[]
admin=env.ref('base.user_admin')
app=env(user=admin.id)
batch=app['saga.import.batch'].search([('state','=','done')],limit=1)
assert batch
company=batch.company_id
finance=env['res.users'].with_context(no_reset_password=True,tracking_disable=True).create({
    'name':'SAGA permission check','login':'saga-permission-test','company_id':1,
    'company_ids':[Command.set([1])],'group_ids':[Command.set([env.ref('base.group_user').id,env.ref('account.group_account_user').id])]})
fin=env(user=finance.id,context={'allowed_company_ids':[1]})
assert not fin['saga.document'].search([])
checks.append('company_isolation')
finance.write({'company_ids':[Command.link(company.id)]})
fin=env(user=finance.id,context={'allowed_company_ids':[company.id]})
assert fin['saga.document'].search_count([])==111
checks.append('authorized_accountant_can_read_documents')
for model in ['saga.import.batch','saga.source.row','saga.payroll.history']:
    try: fin[model].search([])
    except AccessError: checks.append('restricted_'+model)
    else: raise AssertionError('Access unexpectedly granted '+model)
try: batch.with_user(finance).action_import()
except AccessError: checks.append('rpc_import_requires_administrator')
else: raise AssertionError('Accountant allowed import RPC')
try: batch.write({'name':'Edited'})
except UserError: checks.append('completed_batch_immutable')
else: raise AssertionError('Completed batch editable')
try: app['saga.import.batch'].create({'name':'fake','expected_cui':'1','state':'done'})
except AccessError: checks.append('forged_status_rejected')
else: raise AssertionError('Forged state accepted')
other=app['saga.import.batch'].create({'name':batch.name,'expected_cui':batch.expected_cui,'source_confirmed':True,
    'source_file':batch.source_file,'filename':'cont_baza.fdb'})
other.action_analyze()
assert other.state=='blocked' and any('deja importat' in x for x in other.result_json['errors'])
checks.append('duplicate_upload_detected')
# Verify same-CUI protection inside transactional importer, independently of hash check.
other._set(state='ready',extracted=batch.extracted,source_hash=batch.source_hash)
before=env['account.move'].search_count([])
other.action_import()
assert other.state=='failed'
assert env['account.move'].search_count([])==before
assert len(env['res.company'].search([('vat','=',company.vat)]))==1
checks.append('existing_company_blocked_without_partial_writes')
# Independent SQL aggregation compares actual posted entries with each real
# source account side; does not call the importer's normalization routine.
from collections import defaultdict
from decimal import Decimal
expected=defaultdict(lambda:[Decimal(0),Decimal(0)])
data=json.loads(base64.b64decode(batch.extracted))
for row in data['REGISTRU']:
    for index,col in enumerate(['CONT_D','CONT_C']):
        code=row[col].strip()
        if code and code!='%': expected[(row['DATA'][:4],code)][index]+=Decimal(row['SUMA'])
env.cr.execute('''SELECT EXTRACT(YEAR FROM l.date)::integer,(a.code_store ->> l.company_id::text),SUM(l.debit),SUM(l.credit)
FROM account_move_line l JOIN account_account a ON a.id=l.account_id JOIN account_move m ON m.id=l.move_id
WHERE m.saga_batch_id=%s GROUP BY 1,2''',[batch.id])
actual={(str(year),code):[Decimal(str(debit)),Decimal(str(credit))] for year,code,debit,credit in env.cr.fetchall()}
assert dict(expected)==actual,(dict(expected),actual)
checks.append('independent_sql_account_year_debit_credit_match')
env.cr.rollback()
(base/'security-tests.json').write_text(json.dumps({'passed':len(checks),'checks':checks},indent=2),encoding='utf-8')
print('SAGA_SECURITY_AND_RECONCILIATION_OK',len(checks))



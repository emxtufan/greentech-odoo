"""Idempotent local configuration, with exact ledger/residual preservation checks."""
import json
from pathlib import Path

assert env.cr.dbname == 'greentech_financiar_test'
app = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids':[2]})
batch = app['saga.import.batch'].browse(1)
assert batch.state == 'done' and batch.expected_cui == '22465902' and batch.company_id.id == 2
assert batch.source_hash == '9721e5421c842b501892f86040936dc41711ffec2a9be251f16fbc154dc788d1'
def snapshot():
    env.flush_all()
    env.cr.execute('SELECT id, company_id, account_id, debit, credit, amount_residual, amount_residual_currency, full_reconcile_id FROM account_move_line ORDER BY id')
    return env.cr.fetchall()
before = snapshot()
journals = batch._prepare_operations()
assert len(journals) == 3
assert snapshot() == before
assert app['account.journal'].search_count([('company_id','=',2),('type','in',['bank','cash'])]) == 3
balances = []
for journal in journals:
    lines = app['account.move.line'].search([('company_id','=',2),('account_id','=',journal.default_account_id.id),('parent_state','=','posted')])
    balances.append({'journal':journal.name,'account':journal.default_account_id.code,'balance':round(sum(lines.mapped('balance')),2)})
env.cr.commit()
report={'ledger_and_residuals_unchanged':True,'journal_balances':balances,'test_documents_created':False}
(Path.cwd()/'logs/saga-migration/operations-local.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))

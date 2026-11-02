"""Exercise the imported firm's working workflows on the isolated clone; rollback."""
import json
from pathlib import Path
from odoo import Command
from odoo.tools.safe_eval import safe_eval

assert env.cr.dbname.startswith('gt_saga_verify_')
admin = env.ref('base.user_admin')
app = env(user=admin.id, context={'allowed_company_ids': [2], 'tracking_disable': True})
batch = app['saga.import.batch'].search([('state', '=', 'done')], limit=1)
checks = []
def snapshot():
    env.flush_all()
    env.cr.execute('SELECT company_id, account_id, SUM(debit), SUM(credit), COUNT(*) FROM account_move_line GROUP BY 1,2 ORDER BY 1,2')
    return env.cr.fetchall()
before = snapshot()
journals = batch._prepare_operations()
assert len(journals) == 3
assert set(journals.default_account_id.mapped('code')) == {'5121.1','5121.2','5311'}
assert set(batch._prepare_operations().ids) == set(journals.ids)
assert snapshot() == before
checks.append('idempotent_journals_preserve_all_companies_ledger')
for target in ['customers','vendors','sales','purchases','banks','ledger','partners','employees','statements']:
    action = batch.with_context(saga_screen=target).action_open_work()
    assert action['params']['company_id'] == 2
    window = app['ir.actions.act_window'].browse(action['params']['action_id'])
    context = dict(app.context, **safe_eval(window.context, dict(app.context)))
    model = app[window.res_model].with_context(context)
    domain = safe_eval(window.domain, dict(app.context))
    records = model.search(domain)
    if target in {'customers','vendors','sales','purchases'}:
        assert len(records) == {'customers':4,'vendors':17,'sales':56,'purchases':32}[target]
    views = model.get_views([(False, v) for v in window.view_mode.split(',')], {})
    assert views['views']['form']['arch']
checks.append('all_work_actions_company_scoped_views_counts')
duplicate = app['saga.import.batch'].create({'name':batch.name,'expected_cui':batch.expected_cui})
duplicate._set(state='blocked', source_hash=batch.source_hash)
assert duplicate.existing_batch_id == batch
assert duplicate.action_open_work()['params']['company_id'] == 2
checks.append('duplicate_backup_opens_existing_firm')

customer = app['res.partner'].search([('company_id','=',2),('ref','=','SAGA/CLIENTI/00001')],limit=1)
assert customer
income = app['account.account'].search([('company_ids','in',[2]),('code','=','704')],limit=1)
sale = app['account.journal'].search([('company_id','=',2),('code','=','SGV')],limit=1)
invoice = app['account.move'].create({'company_id':2,'journal_id':sale.id,'move_type':'out_invoice',
    'partner_id':customer.id,'invoice_date':'2026-10-20','date':'2026-10-20',
    'invoice_line_ids':[Command.create({'name':'TEST ROLLBACK','quantity':1,'price_unit':100,
                                      'account_id':income.id,'tax_ids':[Command.clear()]})]})
invoice.action_post()
bank = journals.filtered(lambda j:j.default_account_id.code=='5121.1')
method = bank.inbound_payment_method_line_ids[:1]
wizard = app['account.payment.register'].with_context(active_model='account.move',active_ids=invoice.ids).create({
    'journal_id':bank.id,'payment_method_line_id':method.id,'payment_date':'2026-10-20','amount':100})
payments = wizard._create_payments()
assert payments.move_id.state == 'posted'
assert invoice.amount_residual == 0
checks.append('new_invoice_posted_and_payment_recorded')
opening = sum(app['account.move.line'].search([('company_id','=',2),('account_id','=',bank.default_account_id.id),('parent_state','=','posted'),('date','<','2026-10-20')]).mapped('balance'))
statement = app['account.bank.statement'].create({'name':'TEST ROLLBACK EXTRAS','balance_start':opening,
    'balance_end_real':opening+100,'line_ids':[Command.create({'journal_id':bank.id,'date':'2026-10-20',
    'payment_ref':'TEST ROLLBACK','partner_id':customer.id,'amount':100,'counterpart_account_id':method.payment_account_id.id})]})
pair = (payments.move_id.line_ids | statement.line_ids.move_id.line_ids).filtered(
    lambda l:l.account_id == method.payment_account_id and not l.reconciled)
assert len(pair) == 2
pair.reconcile()
assert statement.is_complete and statement.is_valid
assert invoice.payment_state == 'paid'
checks.append('new_real_statement_flow_clears_payment_and_preserves_opening')
vendor = app['res.partner'].search([('company_id','=',2),('supplier_rank','>',0)], limit=1)
purchase = app['account.journal'].search([('company_id','=',2),('code','=','SGA')],limit=1)
expense = app['account.account'].search([('company_ids','in',[2]),('code','=','628')],limit=1)
bill = app['account.move'].create({'company_id':2,'journal_id':purchase.id,'move_type':'in_invoice',
    'partner_id':vendor.id,'invoice_date':'2026-10-20','date':'2026-10-20','ref':'TEST ROLLBACK',
    'invoice_line_ids':[Command.create({'name':'TEST ROLLBACK','quantity':1,'price_unit':50,'account_id':expense.id,'tax_ids':[Command.clear()]})]})
bill.action_post()
assert bill.amount_residual == 50
checks.append('new_vendor_bill_with_imported_vendor')
env.cr.rollback()
assert snapshot() == before
env.cr.rollback()
report={'passed':len(checks),'checks':checks,'test_database':env.cr.dbname,'all_test_transactions_rolled_back':True}
(Path.cwd()/'logs/saga-migration/operations-tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))

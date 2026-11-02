"""Repair demo report configuration without modifying ledger entries."""
import ast
import json
from financial_client import Client, ROOT

c = Client()
s = c.state
assert c.credentials['database'] == 'greentech_financiar_test'
snapshot = {
    'instances': c.search('mis.report.instance', [], ['name', 'analytic_domain']),
    'kpis': c.search('mis.report.kpi', [('report_id', 'in', [s['pnl_template'], s['balance_template']])],
                   ['name', 'expression', 'sequence', 'description']),
}
backup = ROOT / 'logs/demo-reports-before-fix.json'
if not backup.exists():
    backup.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')

# Operational period results must not be cancelled by the closing journal entries.
for key in ['pnl_report', 'budget_report']:
    row = c.read('mis.report.instance', s[key], ['analytic_domain'])
    domain = ast.literal_eval(row['analytic_domain'] or '[]')
    condition = ('move_id.l10n_ro_closing_move', '=', False)
    if condition not in domain:
        domain.append(condition)
    c.write('mis.report.instance', s[key], {'analytic_domain': repr(domain)})

# Include all balance-sheet account classes, including transfer/clearing accounts.
asset_total = "bale[('account_type', 'in', ('asset_receivable','asset_cash','asset_current','asset_non_current','asset_prepayments','asset_fixed'))]"
liability_total = "-bale[('account_type', 'in', ('liability_payable','liability_credit_card','liability_current','liability_non_current'))]"
other_assets = c.ensure('bs_other_assets', 'mis.report.kpi', {
    'report_id': s['balance_template'], 'name': 'other_assets',
    'description': 'Alte active si transferuri in curs',
    'expression': asset_total + ' - fixed - receivables - vat_deductible - cashbank', 'sequence': 5})
other_liabilities = c.ensure('bs_other_liabilities', 'mis.report.kpi', {
    'report_id': s['balance_template'], 'name': 'other_liabilities',
    'description': 'Alte datorii',
    'expression': liability_total + ' - payables - vat_collected', 'sequence': 9})
c.write('mis.report.kpi', other_assets, {'expression': asset_total + ' - fixed - receivables - vat_deductible - cashbank'})
c.write('mis.report.kpi', other_liabilities, {'expression': liability_total + ' - payables - vat_collected'})
changes = {
    'assets': (6, 'fixed + receivables + vat_deductible + cashbank + other_assets'),
    'payables': (7, None), 'vat_collected': (8, None),
    'equity': (10, "-bale[('account_type', 'in', ('equity', 'equity_unaffected'))]"),
    'result': (11, "-bale[('account_type', 'in', ('income','income_other','expense','expense_depreciation','expense_direct_cost'))]"),
    'liabilities': (12, 'payables + vat_collected + other_liabilities + equity + result'),
    'control': (13, None),
}
for key, (sequence, expression) in changes.items():
    values = {'sequence': sequence}
    if expression:
        values['expression'] = expression
    c.write('mis.report.kpi', s['bs_' + key], values)

# Explicit context also supports dashboard/legacy entry paths.
for key in ['pnl_report', 'balance_report', 'budget_report']:
    action = c.read('ir.actions.act_window', s['action_' + key], ['context'])
    context = ast.literal_eval(action['context'] or '{}')
    context.update(active_model='mis.report.instance', active_id=s[key], active_ids=[s[key]])
    c.write('ir.actions.act_window', s['action_' + key], {'context': repr(context)})

# The fixed October dataset belongs to this demo only. No global calendar defaults.
action_id = c.ref('l10n_ro_account_period_close.act_account_period_closing_wizard')
c.write('ir.actions.act_window', action_id, {'context': "{'search_default_closing_id':[active_id], 'default_closing_id': active_id, 'default_date_from': '2026-10-01', 'default_date_to': '2026-10-31'}"})
view_id = c.ref('greentech_closing_feedback.closing_wizard_feedback')
view = c.read('ir.ui.view', view_id, ['arch_db'])['arch_db']
view = view.replace('Verificați luna: implicit este selectată luna anterioară.',
                    'Demonstrația folosește perioada 01.10.2026 – 31.10.2026. Verificați datele înainte de confirmare.')
view = view.replace('Verificați perioada înainte de confirmare.',
                    'Demonstrația folosește perioada 01.10.2026 – 31.10.2026. Verificați datele înainte de confirmare.')
c.write('ir.ui.view', view_id, {'arch_db': view})
c.save()
print('Demo reports repaired; October closing defaults set; ledger unchanged.')

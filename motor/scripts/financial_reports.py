"""Configure live OCA reports and a sample budget for the finance sandbox."""
import json
from financial_client import Client, ROOT

c = Client()
s = c.state
report = c.ensure('pnl_template', 'mis.report', {'name': 'Profit si pierdere - DEMO',
    'description': 'Raport managerial din inregistrarile contabile. Nu este bilantul ANAF.'})
style = c.ensure('money_style', 'mis.report.style', {'name': 'RON - doua zecimale', 'dp': 2, 'dp_inherit': False})
c.write('mis.report', report, {'style_id': style})
kpis = [
    ('revenues', 'Venituri din servicii', '-balp[7%]', 1, True),
    ('services', 'Cheltuieli cu servicii', 'balp[628%]', 2, True),
    ('travel', 'Transport si deplasari', 'balp[625%]', 3, True),
    ('depreciation', 'Amortizare', 'balp[6811%]', 4, True),
    ('other', 'Alte cheltuieli', 'balp[6%] - services - travel - depreciation', 5, True),
    ('costs', 'Cheltuieli totale', 'services + travel + depreciation + other', 6, False),
    ('profit', 'Rezultat inainte de impozit', 'revenues - costs', 7, False),
]
for key, label, expression, order, budgetable in kpis:
    kid = c.ensure('kpi_' + key, 'mis.report.kpi', {'report_id': report, 'name': key,
        'description': label, 'expression': expression, 'sequence': order,
        'budgetable': budgetable, 'compare_method': 'diff'})
    c.write('mis.report.kpi', kid, {'expression': expression, 'sequence': order})
instance = c.ensure('pnl_report', 'mis.report.instance', {'name': '01 - Profit si pierdere / Octombrie 2026',
    'report_id': report, 'date_from': '2026-10-01', 'date_to': '2026-10-31',
    'target_move': 'posted', 'company_id': 1, 'comparison_mode': False})

balance = c.ensure('balance_template', 'mis.report', {'name': 'Situatie patrimoniala - DEMO',
    'description': 'Situatie manageriala active / datorii / capitaluri. Nu este formular ANAF.'})
c.write('mis.report', balance, {'style_id': style})
balance_kpis = [
    ('fixed', 'Imobilizari nete', 'bale[2%]'),
    ('receivables', 'Creante clienti', "bale[('account_type', '=', 'asset_receivable')]"),
    ('vat_deductible', 'TVA deductibila', 'bale[4426%]'),
    ('cashbank', 'Banca si casa', "bale[('account_type', '=', 'asset_cash')]"),
    ('assets', 'Total active', 'fixed + receivables + vat_deductible + cashbank'),
    ('payables', 'Datorii furnizori si finantare asociat', "-bale[('account_type', '=', 'liability_payable')]"),
    ('vat_collected', 'TVA colectata', '-bale[4427%]'),
    ('equity', 'Capitaluri inregistrate', '-bale[1%]'),
    ('result', 'Rezultat curent', '-bale[6%,7%]'),
    ('liabilities', 'Datorii, capitaluri si rezultat', 'payables + vat_collected + equity + result'),
    ('control', 'Control active minus pasiv (trebuie zero)', 'assets - liabilities'),
]
for i, (key, label, expression) in enumerate(balance_kpis):
    c.ensure('bs_' + key, 'mis.report.kpi', {'report_id': balance, 'name': key,
        'description': label, 'expression': expression, 'sequence': i + 1})
c.ensure('balance_report', 'mis.report.instance', {'name': '02 - Situatie patrimoniala / Octombrie 2026',
    'report_id': balance, 'date_from': '2026-01-01', 'date_to': '2026-10-31',
    'target_move': 'posted', 'company_id': 1, 'comparison_mode': False})

budget = c.ensure('budget', 'mis.budget', {'name': 'Buget fictiv - Octombrie 2026', 'report_id': report,
    'date_from': '2026-10-01', 'date_to': '2026-10-31', 'company_id': 1})
for key, amount in [('revenues', 40000), ('services', 15000), ('travel', 300), ('depreciation', 500), ('other', 0)]:
    expression_id = c.read('mis.report.kpi', s['kpi_' + key], ['expression_ids'])['expression_ids'][0]
    c.ensure('budget_' + key, 'mis.budget.item', {'budget_id': budget, 'kpi_expression_id': expression_id,
        'date_from': '2026-10-01', 'date_to': '2026-10-31', 'amount': amount})
c.call('mis.budget', 'action_confirm', [[budget]])
comparison = c.ensure('budget_report', 'mis.report.instance', {'name': '03 - Realizat comparat cu bugetul',
    'report_id': report, 'target_move': 'posted', 'company_id': 1, 'comparison_mode': True})
for key, label, source, sequence in [('actual', 'Realizat', 'actuals', 1), ('budget', 'Buget', 'mis_budget', 2)]:
    vals = {'name': label, 'report_instance_id': comparison, 'sequence': sequence,
        'source': source, 'mode': 'fix', 'manual_date_from': '2026-10-01', 'manual_date_to': '2026-10-31'}
    if source == 'mis_budget':
        vals['source_mis_budget_id'] = budget
    c.ensure('period_' + key, 'mis.report.instance.period', vals)

# Templates ready to close a month using the supported Romanian wizard.
result_account = c.search('account.account', [('code', '=like', '121%')], ['code'], limit=1)[0]['id']
for key, types in [('income', ['income', 'income_other']), ('expense', ['expense', 'expense_direct_cost', 'expense_depreciation'])]:
    accounts = c.search('account.account', [('account_type', 'in', types)], ['code'])
    close_id = c.ensure('close_' + key, 'l10n.ro.account.period.closing', {'name': 'DEMO - Inchidere ' + ('venituri' if key == 'income' else 'cheltuieli'),
        'type': 'selected', 'account_ids': [(6, 0, [a['id'] for a in accounts])],
        'debit_account_id': result_account, 'credit_account_id': result_account,
        'journal_id': s['general_journal'], 'company_id': 1})
    c.write('l10n.ro.account.period.closing', close_id, {'account_ids': [(6, 0, [a['id'] for a in accounts])]})

root = c.ref('account.menu_finance')
reports_menu = c.ensure('reports_menu', 'ir.ui.menu', {'name': 'Rapoarte DEMO', 'parent_id': root, 'sequence': 25})
for key in ['pnl_report', 'balance_report', 'budget_report']:
    title = c.read('mis.report.instance', s[key], ['name'])['name']
    action = c.ensure('action_' + key, 'ir.actions.act_window', {'name': title, 'res_model': 'mis.report.instance',
        'res_id': s[key], 'view_mode': 'form', 'view_id': c.ref('mis_builder.mis_report_instance_result_view_form'),
        'context': repr({'active_model': 'mis.report.instance', 'active_id': s[key], 'active_ids': [s[key]]})})
    c.ensure('menu_' + key, 'ir.ui.menu', {'name': title, 'parent_id': reports_menu,
        'action': 'ir.actions.act_window,' + str(action), 'sequence': s[key]})
    data = c.call('mis.report.instance', 'compute', [[s[key]]])
    (ROOT / 'logs' / ('financial-' + key + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Computed:', title)

dashboard = c.ref('account.open_account_journal_dashboard_kanban')
c.write('res.users', c.uid, {'action_id': dashboard})
c.save()
print('Live financial reports, budget and closing templates ready.')

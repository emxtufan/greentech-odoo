"""Read-only, independent reconciliation of the completed fictional workflow."""
import configparser
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import psycopg2
from psycopg2 import sql
from lxml import html
from workflow_demo_client import Client, ROOT

c = Client()
s = c.state
config = configparser.RawConfigParser()
config.read(ROOT / 'config/odoo.conf', encoding='utf-8-sig')
options = config['options']
connection = psycopg2.connect(host=options['db_host'], port=options['db_port'],
    user=options['db_user'], password=options['db_password'], dbname=c.credentials['database'])
connection.set_session(readonly=True)
checks = {}
def check(name, condition, value):
    if not condition:
        raise AssertionError(f'{name}: {value}')
    checks[name] = value
    print('PASS:', name, value, flush=True)

with connection.cursor() as cur:
    cur.execute("SELECT id,name,state,payment_state,amount_untaxed,amount_tax,amount_total,amount_residual FROM account_move WHERE id=ANY(%s) ORDER BY id",
                ([s['customer_invoice'], s['vendor_bill'], s['expense_move']],))
    rows = cur.fetchall()
    expected = {s['customer_invoice']: (7500, 1575, 9075), s['vendor_bill']: (4000, 840, 4840), s['expense_move']: (200, 0, 200)}
    for row in rows:
        check('document_' + row[1], row[2:4] == ('posted', 'paid') and row[7] == 0
            and row[4:7] == tuple(Decimal(v) for v in expected[row[0]]), list(row[1:]))
    check('all_three_documents', len(rows) == 3, len(rows))
    cur.execute("SELECT m.name,SUM(l.debit),SUM(l.credit) FROM account_move m JOIN account_move_line l ON l.move_id=m.id WHERE m.state='posted' GROUP BY m.id,m.name HAVING ABS(SUM(l.debit-l.credit))>0.005")
    unbalanced = cur.fetchall()
    check('all_posted_entries_balanced', not unbalanced, len(unbalanced))
    cur.execute('SELECT COALESCE(SUM(l.balance),0) FROM account_move_line l JOIN account_move m ON m.id=l.move_id WHERE m.state=\'posted\' AND l.account_id=%s', (s['bank_account'],))
    bank_balance = cur.fetchone()[0]
    check('bank_balance', bank_balance == Decimal('14035'), bank_balance)
    cur.execute("SELECT a.account_type,COALESCE(SUM(l.balance),0),COALESCE(SUM(l.amount_residual),0) FROM account_move_line l JOIN account_move m ON m.id=l.move_id JOIN account_account a ON a.id=l.account_id WHERE m.state='posted' AND a.account_type IN ('asset_receivable','liability_payable') AND l.account_id<>%s GROUP BY a.account_type", (s['funding_account'],))
    settlements = cur.fetchall()
    check('trade_receivables_and_expense_payables_zero', all(row[1] == 0 and row[2] == 0 for row in settlements), settlements)
    cur.execute("SELECT SUM(l.balance) FROM account_move_line l JOIN account_move m ON m.id=l.move_id WHERE m.state='posted' AND l.account_id=%s", (s['funding_account'],))
    funding = cur.fetchone()[0]
    check('fictional_shareholder_funding_liability', funding == -10000, funding)
    cur.execute("SELECT COALESCE(SUM(l.balance),0),COALESCE(SUM(l.amount_residual),0) FROM account_move_line l JOIN account_move m ON m.id=l.move_id WHERE m.state='posted' AND l.account_id=ANY(%s)", ([s['outstanding_in'], s['outstanding_out']],))
    clearing = cur.fetchone()
    check('payments_reconciled_to_bank', clearing == (0, 0), clearing)
    cur.execute("SELECT p.id,p.state,SUM(m.quantity) FROM stock_picking p JOIN stock_move m ON m.picking_id=p.id WHERE p.id=ANY(%s) GROUP BY p.id,p.state", ([s['receipt'], s['delivery']],))
    transfers = cur.fetchall()
    check('receipt_and_delivery_done', len(transfers) == 2 and all(r[1] == 'done' and r[2] == 10 for r in transfers), transfers)
    cur.execute("SELECT COALESCE(SUM(q.quantity),0),COALESCE(SUM(q.reserved_quantity),0) FROM stock_quant q JOIN stock_location l ON l.id=q.location_id WHERE q.product_id=%s AND l.usage='internal'", (s['panel'],))
    quantities = cur.fetchone()
    check('stock_and_reservations_zero', quantities == (0, 0), quantities)
    cur.execute('SELECT state,COUNT(*) FROM project_task WHERE project_id=%s GROUP BY state', (s['project'],))
    tasks = cur.fetchall()
    check('all_four_tasks_complete', tasks == [('1_done', 4)], tasks)
    cur.execute('SELECT unit_amount,amount FROM account_analytic_line WHERE id=%s', (s['timesheet'],))
    timesheet = cur.fetchone()
    check('timesheet_cost', timesheet == (8, -400), timesheet)
    plan_fields = [name for name, values in c.call('account.analytic.line', 'fields_get', [], {'attributes': ['type']}).items()
                   if name == 'account_id' or name.startswith('x_plan') and name.endswith('_id')]
    domain = sql.SQL(' OR ').join(sql.SQL('{}=%s').format(sql.Identifier(name)) for name in plan_fields)
    cur.execute(sql.SQL('SELECT SUM(amount) FROM account_analytic_line WHERE ') + domain, [s['analytic']] * len(plan_fields))
    margin = cur.fetchone()[0]
    check('analytic_project_margin', margin == 2900, margin)
    cur.execute("SELECT -SUM(l.balance) FROM account_move_line l JOIN account_move m ON m.id=l.move_id JOIN account_account a ON a.id=l.account_id WHERE m.state='posted' AND a.account_type IN ('income','income_other','expense','expense_depreciation','expense_direct_cost')")
    accounting_result = cur.fetchone()[0]
    check('accounting_result_before_payroll_and_tax', accounting_result == 3300, accounting_result)
    cur.execute("SELECT count(*) FROM mail_mail WHERE state IN ('outgoing','sent')")
    messages = cur.fetchone()[0]
    check('no_outgoing_or_sent_emails', messages == 0, messages)
connection.close()

panel = c.call('project.project', 'get_panel_data', [[s['project']]])
profit = panel['profitability_items']
check('native_project_profitability', profit['revenues']['total']['invoiced'] == 7500
    and profit['costs']['total']['billed'] == -4600,
    {'revenue': profit['revenues']['total']['invoiced'], 'cost': profit['costs']['total']['billed']})

models = {'project': 'project.project', 'sale': 'sale.order', 'purchase': 'purchase.order',
          'receipt': 'stock.picking', 'delivery': 'stock.picking', 'customer_invoice': 'account.move',
          'vendor_bill': 'account.move', 'expense': 'hr.expense', 'bank_statement': 'account.bank.statement'}
for key, model in models.items():
    response = c.session.get(f'{c.base}/odoo/{model}/{s[key]}?db={c.credentials["database"]}', timeout=30)
    check('http_' + key, response.status_code == 200 and 'odoo.__session_info__' in response.text, response.status_code)
    view = c.call(model, 'get_views', [], {'views': [[False, 'form']], 'options': {'toolbar': True}})
    check('form_' + key, bool(view.get('views', {}).get('form')), True)

response = c.session.get(c.base + '/odoo', timeout=30)
assets = html.fromstring(response.text).xpath('//script[@src]/@src | //link[@rel="stylesheet"]/@href')
for asset in assets:
    if asset.startswith('/'):
        r = c.session.get(c.base + asset, timeout=90)
        check('asset_' + asset.rsplit('/', 1)[-1], r.status_code == 200, len(r.content))

for key, report in [('customer_invoice', 'account.report_invoice'), ('sale', 'sale.report_saleorder'),
                    ('purchase', 'purchase.report_purchaseorder'), ('delivery', 'stock.report_deliveryslip')]:
    r = c.session.get(f'{c.base}/report/html/{report}/{s[key]}', timeout=60)
    check('print_preview_' + key, r.status_code == 200 and 'Internal Server Error' not in r.text, r.status_code)

result = {'database': c.credentials['database'], 'checked_at': datetime.now().isoformat(),
          'checks': checks, 'project_panel': panel, 'records': s,
          'amounts': {'revenue_net': 7500, 'materials_net': 4000, 'expense_no_deducted_vat': 200,
                     'timesheet_hours': 8, 'timesheet_cost_estimate': 400, 'analytic_margin': 2900,
                     'accounting_result_before_payroll_and_tax': 3300,
                     'customer_invoice_gross': 9075, 'vendor_bill_gross': 4840,
                     'net_vat_for_example': 735, 'seed_funding': 10000, 'bank_closing_balance': 14035}}
(ROOT / 'logs/workflow-verification.json').write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
print('Independent reconciliation and application verification complete.', flush=True)

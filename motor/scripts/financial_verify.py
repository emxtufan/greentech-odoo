"""Independent ledger reconciliation plus native HTTP report and UI-contract tests."""
import configparser
from datetime import datetime
from decimal import Decimal
from io import BytesIO
import json
import re
from zipfile import ZipFile
from lxml import html
import psycopg2
from financial_client import Client, ROOT

c = Client()
s = c.state
checks = {}
exports = ROOT / 'logs/financial-exports'
exports.mkdir(exist_ok=True)

def check(name, condition, value):
    if not condition:
        raise AssertionError(f'{name}: {value}')
    checks[name] = value
    print('PASS:', name, str(value)[:180], flush=True)

cfg = configparser.RawConfigParser()
cfg.read(ROOT / 'config/odoo-financiar.conf', encoding='utf-8')
opt = cfg['options']
conn = psycopg2.connect(host=opt['db_host'], port=opt['db_port'], user=opt['db_user'],
    password=opt['db_password'], dbname='greentech_financiar_test')
conn.set_session(readonly=True)
expected = s['expected_documents']
money = lambda x: Decimal(str(x)).quantize(Decimal('.01'))
net_revenue = sum(money(v['net']) for k,v in expected.items() if k.startswith('sale_') and v['posted']) - money(expected['sale_8']['net'])
net_cost = sum(money(v['net']) for k,v in expected.items() if k.startswith('purchase_') and v['posted']) + 150 + 500
receivable = sum(money(v['total']) - money(v['paid']) for k,v in expected.items() if k.startswith('sale_') and v['posted'] and k != 'sale_8')
payable = sum(money(v['total']) - money(v['paid']) for k,v in expected.items() if k.startswith('purchase_') and v['posted'])
with conn.cursor() as cur:
    for key, e in expected.items():
        cur.execute('SELECT name,state,amount_untaxed,amount_tax,amount_total,amount_residual,payment_state FROM account_move WHERE id=%s', (e['id'],))
        row = cur.fetchone()
        residual = 0 if key == 'sale_8' else money(e['total']) - money(e['paid'])
        valid = row[1] == ('posted' if e['posted'] else 'draft') and row[2:5] == tuple(money(e[x]) for x in ['net','vat','total'])
        if e['posted']:
            valid = valid and row[5] == residual
        check('invoice_' + key, valid, list(row))
    cur.execute("SELECT m.id FROM account_move m JOIN account_move_line l ON l.move_id=m.id WHERE m.state='posted' GROUP BY m.id HAVING abs(SUM(l.debit-l.credit))>0.005")
    check('all_posted_entries_balanced', not cur.fetchall(), True)
    for key in ['bank', 'cash']:
        cur.execute("SELECT SUM(l.balance) FROM account_move_line l JOIN account_move m ON m.id=l.move_id WHERE m.state='posted' AND l.account_id=%s", (s[key+'_account'],))
        actual = cur.fetchone()[0]
        check(key+'_balance', actual == money(s['expected_'+key+'_balance']), actual)
    for typ, wanted in [('asset_receivable', receivable), ('liability_payable', -payable)]:
        cur.execute("SELECT SUM(l.balance) FROM account_move_line l JOIN account_move m ON m.id=l.move_id JOIN account_account a ON a.id=l.account_id WHERE m.state='posted' AND a.account_type=%s AND a.id<>%s", (typ,s['funding_account']))
        actual = cur.fetchone()[0]
        check(typ, actual == wanted, actual)
    cur.execute("SELECT -SUM(l.balance) FROM account_move_line l JOIN account_move m ON m.id=l.move_id JOIN account_account a ON a.id=l.account_id WHERE m.state='posted' AND a.account_type IN ('income','income_other','expense','expense_depreciation','expense_direct_cost')")
    actual_profit = cur.fetchone()[0]
    check('ledger_profit', actual_profit == net_revenue - net_cost, actual_profit)
    cur.execute("SELECT COALESCE(SUM(l.balance),0),COALESCE(SUM(l.amount_residual),0) FROM account_move_line l JOIN account_move m ON m.id=l.move_id WHERE m.state='posted' AND l.account_id=ANY(%s)", ([s['outstanding_in'],s['outstanding_out']],))
    check('payment_clearing_zero', cur.fetchone() == (0,0), True)
    cur.execute("SELECT COUNT(*) FROM account_asset_line WHERE asset_id=%s AND type='depreciate'", (s['asset'],))
    check('asset_24_month_schedule', cur.fetchone()[0] == 24, 24)
    cur.execute("SELECT COUNT(*) FROM account_asset_line WHERE asset_id=%s AND type='depreciate' AND amount=500", (s['asset'],))
    check('asset_500_per_month', cur.fetchone()[0] == 24, 500)
    cur.execute('SELECT COUNT(*) FROM mail_mail')
    check('no_outgoing_messages', cur.fetchone()[0] == 0, 0)
    cur.execute('SELECT COUNT(*) FROM ir_cron WHERE active')
    check('scheduled_transmission_disabled', cur.fetchone()[0] == 0, 0)
conn.close()

for key in ['pnl_report','balance_report','budget_report']:
    data = c.call('mis.report.instance','compute',[[s[key]]])
    check('report_'+key+'_no_formula_errors', all(not cell.get('val_r','').startswith('#') for row in data['body'] for cell in row['cells']), True)
    rows = {row['label']: row['cells'] for row in data['body']}
    if key == 'pnl_report':
        check('pnl_matches_independent_ledger', money(rows['Rezultat inainte de impozit'][0]['val']) == actual_profit, rows['Rezultat inainte de impozit'][0]['val'])
    if key == 'balance_report':
        check('assets_equal_liabilities_plus_equity', rows['Control active minus pasiv (trebuie zero)'][0]['val'] == 0, 0)
    if key == 'budget_report':
        check('budget_profit', rows['Rezultat inainte de impozit'][1]['val'] == 24200, 24200)
    (exports / (key + '.json')).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

modules = c.search('ir.module.module',[('state','=','installed')],['name','installed_version'])
wanted_modules = json.loads((ROOT / 'logs/financial-modules.json').read_text())
check('selected_modules_installed', set(wanted_modules).issubset({m['name'] for m in modules}), len(modules))
check('financial_only_no_project_sales_stock_payroll', not {'project','sale','stock','hr_payroll'}.intersection(m['name'] for m in modules), True)
statements = c.search('account.bank.statement',[],['name','is_complete','is_valid'])
check('bank_and_cash_statements_valid', all(x['is_complete'] and x['is_valid'] for x in statements), statements)
statement_lines = c.search('account.bank.statement.line',[],['is_reconciled'])
check('all_statement_lines_reconciled', all(x['is_reconciled'] for x in statement_lines), len(statement_lines))
for model in ['account.move','account.payment','account.bank.statement','account.bank.statement.line',
              'account.asset','account.asset.profile','mis.report.instance','mis.budget',
              'l10n.ro.account.period.closing','trial.balance.report.wizard','general.ledger.report.wizard']:
    view = c.call(model,'get_views',[],{'views':[[False,'form']], 'options':{'toolbar':True}})
    check('form_'+model, bool(view.get('views')), True)

page = c.session.get(c.base+'/odoo',timeout=45)
check('app_page', page.status_code==200 and 'web.assets_web' in page.text, page.status_code)
tree = html.fromstring(page.content)
assets = [url for url in tree.xpath('//script/@src | //link[@rel="stylesheet"]/@href') if url.startswith('/web/assets/')]
for url in assets:
    response = c.session.get(c.base+url,timeout=120)
    check('asset_'+url.split('/')[-1], response.status_code==200 and len(response.content)>100, len(response.content))

def fetch_report(label, action, converter, ids=None):
    ctx = {**c.context, **action.get('context',{})}
    if ids:
        ctx.update(active_ids=ids,active_id=ids[0])
    path = f"/report/{converter}/{action['report_name']}"
    if ids:
        path += '/' + ','.join(map(str,ids))
    response = c.session.get(c.base+path,params={'options':json.dumps(action.get('data') or {}),
        'context':json.dumps(ctx)},timeout=120)
    check('render_'+label+'_'+converter, response.status_code==200 and 'Traceback' not in response.text[:1500] if converter=='html' else response.status_code==200 and response.content[:2]==b'PK',
          {'status':response.status_code,'bytes':len(response.content)})
    if converter=='xlsx':
        with ZipFile(BytesIO(response.content)) as z:
            check('xlsx_structure_'+label, '[Content_Types].xml' in z.namelist() and any(n.startswith('xl/worksheets/') for n in z.namelist()), True)
    (exports/(label+'.'+('html' if converter=='html' else 'xlsx'))).write_bytes(response.content)
    return response

wizard_specs = [
    ('balanta', 'trial.balance.report.wizard', {'date_from':'2026-10-01','date_to':'2026-10-31','target_move':'posted'}),
    ('carte_mare', 'general.ledger.report.wizard', {'date_from':'2026-10-01','date_to':'2026-10-31','target_move':'posted'}),
    ('registru_jurnal', 'journal.ledger.report.wizard', {'date_from':'2026-10-01','date_to':'2026-10-31','move_target':'posted'}),
    ('tva', 'vat.report.wizard', {'date_from':'2026-10-01','date_to':'2026-10-31','based_on':'taxgroups'}),
]
ar_accounts = c.search('account.account',[('account_type','=','asset_receivable')],['code'])
wizard_specs.append(('scadente_clienti','aged.partner.balance.report.wizard', {'date_at':'2026-10-31',
    'account_ids':[(6,0,[a['id'] for a in ar_accounts])], 'receivable_accounts_only':True}))
for label, model, values in wizard_specs:
    wizard = c.call(model,'create',[[{**values,'company_id':1}]])[0]
    for converter, method in [('html','button_export_html'),('xlsx','button_export_xlsx')]:
        action = c.call(model,method,[[wizard]])
        fetch_report(label,action,converter,[wizard])
for key in ['pnl_report','balance_report','budget_report']:
    action = c.call('mis.report.instance','export_xls',[[s[key]]])
    fetch_report(key,action,'xlsx',[s[key]])
    action = c.call('mis.report.instance','print_pdf',[[s[key]]])
    fetch_report(key,action,'html',[s[key]])
asset_wiz = c.call('wiz.account.asset.report','create',[[{'date_from':'2026-01-01','date_to':'2026-10-31','company_id':1}]])[0]
fetch_report('mijloace_fixe',c.call('wiz.account.asset.report','xls_export',[[asset_wiz]],
    context={'active_model':'wiz.account.asset.report','active_ids':[asset_wiz],'active_id':asset_wiz}),'xlsx',[asset_wiz])
fetch_report('factura_client',{'report_name':'account.report_invoice_with_payments'},'html',[s['sale_0']])
fetch_report('factura_storno',{'report_name':'account.report_invoice_with_payments'},'html',[s['credit_note']])
pdf_state = c.call('ir.actions.report','get_wkhtmltopdf_state')
if pdf_state == 'ok':
    for label, path, params in [
        ('invoice', '/report/pdf/account.report_invoice_with_payments/' + str(s['sale_0']), {}),
        ('credit_note', '/report/pdf/account.report_invoice_with_payments/' + str(s['credit_note']), {}),
    ]:
        response = c.session.get(c.base + path, params=params, timeout=120)
        check('native_pdf_' + label, response.status_code == 200 and response.content.startswith(b'%PDF-'), len(response.content))
        (exports / (label + '.pdf')).write_bytes(response.content)
result = {'verified_at':datetime.now().isoformat(),'database':c.credentials['database'],
    'checks':checks, 'modules':modules,
    'summary':{'revenue':float(net_revenue),'costs':float(net_cost),'profit':float(actual_profit),
        'bank':s['expected_bank_balance'],'cash':1850,'customer_receivable':float(receivable),
        'supplier_payable':float(payable),'asset_gross':12000,'asset_depreciation':500,'asset_net':11500},
    'limitations':{'pdf_engine':pdf_state,'visual_browser_check':False,'anaf_submission':False,
        'payroll_and_statutory_declarations':False}}
(ROOT/'logs/financial-verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
print('Saved verification report:', len(checks), 'checks. PDF engine:', pdf_state)

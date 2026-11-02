"""Repeatable fictional finance scenario, using Odoo business methods over RPC."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import random
from financial_client import Client

c = Client()
s = c.state
rng = random.Random(20261019)
TODAY = '2026-10-19'
START = '2026-10-01'

def account(prefix):
    rows = c.search('account.account', [('code', '=like', prefix + '%')], ['code'], limit=1)
    if not rows:
        raise RuntimeError('Missing Romanian account: ' + prefix)
    return rows[0]['id']

def post(move):
    if c.read('account.move', move, ['state'])['state'] == 'draft':
        c.call('account.move', 'action_post', [[move]])

groups = ['account.group_account_manager', 'account.group_account_basic', 'account.group_account_user',
          'analytic.group_analytic_accounting']
c.write('res.users', c.uid, {'group_ids': [(4, c.ref(g)) for g in groups]})
c = Client()
s = c.state
c.write('res.company', 1, {'name': 'GreenTech Financiar DEMO - date fictive',
    'street': 'Strada Demonstratiei 10 - adresa fictiva', 'city': 'Bucuresti',
    'email': False, 'phone': False, 'website': False,
    'report_footer': 'DEMONSTRATIE - DATE FICTIVE - FARA VALOARE FISCALA',
    'external_report_layout_id': c.ref('web.external_layout_standard'),
    'account_fiscal_country_id': c.ref('base.ro')})
cron_ids = c.call('ir.cron', 'search', [[]])
c.call('ir.cron', 'write', [cron_ids, {'active': False}])
root_menu = c.ref('account.menu_finance')
c.write('ir.ui.menu', root_menu, {'name': 'Financiar', 'sequence': 1})
for param_key, param_value in [('web.base.url', c.base), ('web.base.url.freeze', 'True'), ('report.url', c.base)]:
    c.call('ir.config_parameter', 'set_param', [param_key, param_value])

s['income_account'] = account('704')
s['expense_account'] = account('628')
s['funding_account'] = account('4551')
s['asset_account'] = account('214')
s['depreciation_account'] = account('2814')
s['depreciation_expense'] = account('6811')
# In this chart snapshot 28xx was classified as a P&L expense. Accumulated
# depreciation is a contra-asset; keep its balance on the balance sheet.
contra_assets = c.search('account.account', [('code', '=like', '28%'), ('account_type', '=', 'expense_depreciation')], ['code'])
if contra_assets:
    c.call('account.account', 'write', [[a['id'] for a in contra_assets], {'account_type': 'asset_fixed'}])
c.write('account.account', s['depreciation_expense'], {'account_type': 'expense_depreciation'})
s['sale_tax'] = c.search('account.tax', [('type_tax_use', '=', 'sale'), ('name', '=', '21% S')], ['name'])[0]['id']
s['buy_tax'] = c.search('account.tax', [('type_tax_use', '=', 'purchase'), ('name', '=', '21% S')], ['name'])[0]['id']
s['asset_tax'] = c.read('res.company', 1, ['account_purchase_tax_id'])['account_purchase_tax_id'][0]
c.save()

for i, name in enumerate(['Solar Atelier', 'Nord Instal', 'Eco Cladiri', 'Delta Service', 'Lumina Construct', 'Orizont Office']):
    c.ensure(f'customer_{i}', 'res.partner', {'name': name + ' [DEMO]', 'is_company': True,
        'customer_rank': 1, 'country_id': c.ref('base.ro'), 'city': 'Bucuresti',
        'comment': 'Societate fictiva pentru test. Fara CUI, email sau cont bancar real.'})
for i, name in enumerate(['Tech Echipamente', 'Birou Confort', 'Transport Sprint', 'Consult Expert', 'Utilitati Verzi']):
    c.ensure(f'vendor_{i}', 'res.partner', {'name': name + ' [DEMO]', 'is_company': True,
        'supplier_rank': 1, 'country_id': c.ref('base.ro'),
        'comment': 'Furnizor fictiv - demonstratie.'})

plan = c.ensure('analytic_plan', 'account.analytic.plan', {'name': 'Centre de cost DEMO'})
for i, name in enumerate(['Administrativ', 'Operatiuni', 'Comercial']):
    c.ensure(f'analytic_{i}', 'account.analytic.account', {'name': name + ' [DEMO]', 'plan_id': plan, 'company_id': 1})

bank_account = c.ensure('bank_account', 'account.account', {'name': 'Banca simulata RON', 'code': '512190', 'account_type': 'asset_cash'})
cash_account = c.ensure('cash_account', 'account.account', {'name': 'Casa simulata RON', 'code': '531190', 'account_type': 'asset_cash'})
incoming = c.ensure('outstanding_in', 'account.account', {'name': 'Incasari in curs DEMO', 'code': '512191', 'account_type': 'asset_current', 'reconcile': True})
outgoing = c.ensure('outstanding_out', 'account.account', {'name': 'Plati in curs DEMO', 'code': '512192', 'account_type': 'asset_current', 'reconcile': True})
bank = c.ensure('bank_journal', 'account.journal', {'name': 'Banca DEMO RON', 'code': 'BDMO', 'type': 'bank', 'default_account_id': bank_account})
cash = c.ensure('cash_journal', 'account.journal', {'name': 'Casa DEMO RON', 'code': 'CDMO', 'type': 'cash', 'default_account_id': cash_account})
general = c.ensure('general_journal', 'account.journal', {'name': 'Operatiuni diverse DEMO', 'code': 'ODMO', 'type': 'general'})
for method in c.search('account.payment.method.line', [('journal_id', '=', bank)], ['payment_type']):
    c.write('account.payment.method.line', method['id'], {'payment_account_id': incoming if method['payment_type'] == 'inbound' else outgoing})
    s['method_' + method['payment_type']] = method['id']
c.save()

products = [('Consultanta tehnica', 1500), ('Revizie instalatie', 850), ('Configurare software', 2200), ('Mentenanta lunara', 650)]
for i, (name, price) in enumerate(products):
    c.ensure(f'product_{i}', 'product.product', {'name': name + ' [DEMO]', 'type': 'service',
        'default_code': f'DEMO-S{i+1:02}', 'list_price': price,
        'property_account_income_id': s['income_account'], 'property_account_expense_id': s['expense_account'],
        'taxes_id': [(6, 0, [s['sale_tax']])], 'supplier_taxes_id': [(6, 0, [s['buy_tax']])]})

expected = {}
for kind, count in [('sale', 12), ('purchase', 8)]:
    for i in range(count):
        key = f'{kind}_{i}'
        price = rng.choice([450, 650, 850, 1200, 1500, 2200])
        qty = rng.randint(1, 4)
        draft = i >= (10 if kind == 'sale' else 7)
        partner = s[f'customer_{i % 6}'] if kind == 'sale' else s[f'vendor_{i % 5}']
        day = f'2026-10-{1 + i:02}'
        tax = s['sale_tax'] if kind == 'sale' else s['buy_tax']
        line = {'name': products[i % 4][0] + ' - TEST', 'quantity': qty, 'price_unit': price,
            'product_id': s[f'product_{i % 4}'], 'account_id': s['income_account'] if kind == 'sale' else s['expense_account'],
            'tax_ids': [(6, 0, [tax])], 'analytic_distribution': {str(s[f'analytic_{i % 3}']): 100}}
        move = c.ensure(key, 'account.move', {'move_type': 'out_invoice' if kind == 'sale' else 'in_invoice',
            'partner_id': partner, 'invoice_date': day, 'date': day, 'invoice_date_due': '2026-10-15' if i % 2 else '2026-11-05',
            'ref': f'DEMO-{kind.upper()}-{i+1:03}', 'invoice_payment_term_id': False,
            'narration': '<p>DATE FICTIVE - DOCUMENT DE TEST - FARA VALOARE FISCALA</p>',
            'invoice_line_ids': [(0, 0, line)]})
        if not draft:
            post(move)
        net = Decimal(price) * qty
        vat = (net * Decimal('0.21')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        expected[key] = {'id': move, 'net': float(net), 'vat': float(vat), 'total': float(net + vat),
                         'posted': not draft, 'partner': partner, 'paid': 0.0}
s['expected_documents'] = expected
c.save()

# A real reversal wizard links the credit note to its source invoice.
original = s['sale_8']
if 'credit_note' not in s:
    context = {'active_model': 'account.move', 'active_ids': [original], 'active_id': original}
    wiz = c.call('account.move.reversal', 'create', [[{'date': TODAY, 'reason': 'DEMO - anulare integrala serviciu',
        'move_ids': [(6, 0, [original])], 'company_id': 1,
        'journal_id': c.read('account.move', original, ['journal_id'])['journal_id'][0]}]], context=context)[0]
    c.call('account.move.reversal', 'reverse_moves', [[wiz]], context=context)
    s['credit_note'] = c.read('account.move.reversal', wiz, ['new_move_ids'])['new_move_ids'][0]
    c.save()
post(s['credit_note'])
lines = c.search('account.move.line', [('move_id', 'in', [original, s['credit_note']]),
    ('account_id.account_type', '=', 'asset_receivable'), ('reconciled', '=', False)], ['balance'])
if lines:
    c.call('account.move.line', 'reconcile', [[x['id'] for x in lines]])

# Capital purchase: the vendor bill automatically creates the OCA asset.
profile = c.ensure('asset_profile', 'account.asset.profile', {'name': 'DEMO - Echipament IT / 24 luni',
    'account_asset_id': s['asset_account'], 'account_depreciation_id': s['depreciation_account'],
    'account_expense_depreciation_id': s['depreciation_expense'], 'journal_id': general,
    'method': 'linear', 'method_time': 'number', 'method_number': 24, 'method_period': 'month',
    'prorata': False, 'open_asset': False, 'company_id': 1})
asset_bill = c.ensure('asset_bill', 'account.move', {'move_type': 'in_invoice', 'partner_id': s['vendor_0'],
    'invoice_date': '2026-09-25', 'date': '2026-09-25', 'ref': 'DEMO-MF-001',
    'invoice_line_ids': [(0, 0, {'name': 'Server contabilitate [DEMO]', 'quantity': 1, 'price_unit': 12000,
        'account_id': s['asset_account'], 'asset_profile_id': profile, 'tax_ids': [(6, 0, [s['asset_tax']])]})]})
post(asset_bill)
asset_line = c.search('account.move.line', [('move_id', '=', asset_bill), ('asset_id', '!=', False)], ['asset_id'])[0]
s['asset'] = asset_line['asset_id'][0]
c.save()
asset = c.read('account.asset', s['asset'], ['state'])
if asset['state'] == 'draft':
    c.write('account.asset', s['asset'], {'date_start': START})
    c.call('account.asset', 'validate', [[s['asset']]])
if 'depreciation_move' not in s:
    depreciation = c.search('account.asset.line', [('asset_id', '=', s['asset']), ('type', '=', 'depreciate')], ['line_date', 'amount', 'move_id'])
    first = sorted(depreciation, key=lambda row: row['line_date'])[0]
    moves = [first['move_id'][0]] if first['move_id'] else c.call('account.asset.line', 'create_move', [[first['id']]])
    s['depreciation_move'] = moves[0]
    s['depreciation_amount'] = first['amount']
    c.save()

statement = c.ensure('bank_statement', 'account.bank.statement', {'name': 'EXTRAS DEMO OCTOMBRIE 2026', 'balance_start': 0})
c.ensure('funding_line', 'account.bank.statement.line', {'statement_id': statement, 'journal_id': bank,
    'date': START, 'payment_ref': 'DEMO - finantare fictiva asociat', 'amount': 100000,
    'counterpart_account_id': s['funding_account']})

def pay(key, move, amount, direction):
    if key not in s:
        ctx = {'active_model': 'account.move', 'active_ids': [move], 'active_id': move}
        wizard = c.call('account.payment.register', 'create', [[{'journal_id': bank,
            'payment_method_line_id': s['method_' + direction], 'amount': amount,
            'payment_date': TODAY, 'communication': 'DEMO - ' + key}]], context=ctx)[0]
        action = c.call('account.payment.register', 'action_create_payments', [[wizard]], context=ctx)
        s[key] = action['res_id']
        c.save()
    payment = c.read('account.payment', s[key], ['move_id', 'partner_id'])
    clearing = incoming if direction == 'inbound' else outgoing
    stmt = c.ensure('statement_' + key, 'account.bank.statement.line', {'statement_id': statement,
        'journal_id': bank, 'date': TODAY, 'payment_ref': 'EXTRAS FICTIV - ' + key,
        'partner_id': payment['partner_id'][0], 'amount': amount if direction == 'inbound' else -amount,
        'counterpart_account_id': clearing})
    statement_move = c.read('account.bank.statement.line', stmt, ['move_id'])['move_id'][0]
    pairs = c.search('account.move.line', [('move_id', 'in', [payment['move_id'][0], statement_move]),
        ('account_id', '=', clearing), ('reconciled', '=', False)], ['balance'])
    if pairs:
        assert len(pairs) == 2 and abs(sum(p['balance'] for p in pairs)) < .005
        c.call('account.move.line', 'reconcile', [[p['id'] for p in pairs]])

for i in range(4):
    row = expected[f'sale_{i}']
    pay(f'payment_sale_{i}', row['id'], row['total'], 'inbound')
    row['paid'] = row['total']
row = expected['sale_4']
pay('payment_sale_partial', row['id'], round(row['total'] / 2, 2), 'inbound')
row['paid'] = round(row['total'] / 2, 2)
for i in range(3):
    row = expected[f'purchase_{i}']
    pay(f'payment_purchase_{i}', row['id'], row['total'], 'outbound')
    row['paid'] = row['total']
pay('payment_asset', asset_bill, 14520, 'outbound')

c.ensure('cash_transfer', 'account.bank.statement.line', {'statement_id': statement, 'journal_id': bank,
    'date': TODAY, 'payment_ref': 'DEMO - transfer banca in casa', 'amount': -2000, 'counterpart_account_id': cash_account})
cash_statement = c.ensure('cash_statement', 'account.bank.statement', {'name': 'REGISTRU CASA DEMO',
    'balance_start': 2000, 'balance_end_real': 1850})
c.ensure('cash_expense', 'account.bank.statement.line', {'statement_id': cash_statement, 'journal_id': cash,
    'date': TODAY, 'payment_ref': 'DEMO - transport local fara TVA dedusa', 'amount': -150,
    'counterpart_account_id': account('625')})
bank_balance = 100000 + sum(v['paid'] for k,v in expected.items() if k.startswith('sale_')) - sum(v['paid'] for k,v in expected.items() if k.startswith('purchase_')) - 14520 - 2000
c.write('account.bank.statement', statement, {'balance_end_real': bank_balance})
s['expected_documents'] = expected
s['expected_bank_balance'] = bank_balance
s['expected_cash_balance'] = 1850
c.save()
print('Financial scenario complete: invoices, bills, reversal, payments, statements, cash and asset.')

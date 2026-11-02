from workflow_demo_client import Client

c = Client()
groups = ['analytic.group_analytic_accounting', 'account.group_account_manager',
          'account.group_account_basic', 'account.group_account_user',
          'hr_expense.group_hr_expense_manager', 'project.group_project_manager']
c.write('res.users', c.uid, {'group_ids': [(4, c.ref(group)) for group in groups]})
c = Client()
c.write('res.company', 1, {'name': 'GreenTech DEMO - exclusiv test',
                          'inventory_valuation': 'periodic', 'cost_method': 'standard'})
# This fresh database contains only fictional data; disable scheduled external activity.
cron_ids = c.call('ir.cron', 'search', [[]])
if cron_ids:
    c.call('ir.cron', 'write', [cron_ids, {'active': False}])

def account(prefix):
    rows = c.search('account.account', [('code', '=like', prefix + '%')], ['code', 'name'], limit=1)
    if not rows:
        raise RuntimeError('Missing Romanian account ' + prefix)
    return rows[0]['id']

company = c.read('res.company', 1, ['account_sale_tax_id', 'account_purchase_tax_id'])
sale_tax = company['account_sale_tax_id'][0]
purchase_tax = company['account_purchase_tax_id'][0]
service_tax = c.search('account.tax', [('type_tax_use', '=', 'sale'), ('name', '=', '21% S')], ['name'])[0]['id']
c.state.update(sale_tax=sale_tax, purchase_tax=purchase_tax, service_tax=service_tax)
c.save()

customer = c.ensure('customer', 'res.partner', {'name': 'CLIENT DEMO - Hala Solara',
    'is_company': True, 'customer_rank': 1, 'country_id': c.ref('base.ro'),
    'street': 'Adresa fictiva pentru demonstratie', 'city': 'Bucuresti', 'comment': 'DATE FICTIVE - NU TRANSMITE DOCUMENTE'})
vendor = c.ensure('vendor', 'res.partner', {'name': 'FURNIZOR DEMO - Panouri Solare',
    'is_company': True, 'supplier_rank': 1, 'country_id': c.ref('base.ro'),
    'comment': 'DATE FICTIVE - NU TRANSMITE DOCUMENTE'})
plan = c.ensure('analytic_plan', 'account.analytic.plan', {'name': 'Proiecte demonstratie', 'default_applicability': 'optional'})
analytic = c.ensure('analytic', 'account.analytic.account', {'name': 'TEST - Sistem fotovoltaic 5 kW',
    'plan_id': plan, 'partner_id': customer, 'company_id': 1, 'code': 'TEST-PV-001'})
project = c.ensure('project', 'project.project', {'name': 'TEST - Montaj fotovoltaic 5 kW',
    'partner_id': customer, 'account_id': analytic, 'allow_timesheets': True,
    'allow_billable': True, 'user_id': c.uid,
    'description': '<p>Demonstratie integrata: proiect, achizitie, stoc, montaj, cheltuiala, vanzare, facturi si plati. Exclusiv date fictive.</p>'})
employee = c.ensure('employee', 'hr.employee', {'name': 'Alex Instalator [TEST]',
    'hourly_cost': 50.0, 'expense_manager_id': c.uid, 'company_id': 1})
category = c.ensure('category', 'product.category', {'name': 'TEST - Materiale fotovoltaice',
    'property_cost_method': 'standard', 'property_valuation': 'periodic',
    'property_account_income_categ_id': account('707'), 'property_account_expense_categ_id': account('607')})
panel = c.ensure('panel', 'product.product', {'name': 'TEST - Panou fotovoltaic 500 W',
    'default_code': 'TEST-PV500', 'type': 'consu', 'is_storable': True,
    'categ_id': category, 'list_price': 600.0, 'standard_price': 400.0,
    'sale_ok': True, 'purchase_ok': True, 'invoice_policy': 'delivery', 'purchase_method': 'receive',
    'taxes_id': [(6, 0, [sale_tax])], 'supplier_taxes_id': [(6, 0, [purchase_tax])]})
c.ensure('vendor_price', 'product.supplierinfo', {'partner_id': vendor, 'product_id': panel,
    'product_tmpl_id': c.read('product.product', panel, ['product_tmpl_id'])['product_tmpl_id'][0],
    'min_qty': 1, 'price': 400, 'delay': 1})
service = c.ensure('service', 'product.product', {'name': 'TEST - Montaj si punere in functiune',
    'default_code': 'TEST-MONTAJ', 'type': 'service', 'sale_ok': True, 'purchase_ok': False,
    'list_price': 1500, 'invoice_policy': 'order', 'service_tracking': 'task_global_project',
    'project_id': project, 'property_account_income_id': account('704'),
    'taxes_id': [(6, 0, [service_tax])], 'supplier_taxes_id': [(6, 0, [])]})
c.ensure('travel_product', 'product.product', {'name': 'TEST - Deplasare fara TVA dedusa',
    'type': 'service', 'can_be_expensed': True, 'expense_policy': 'no', 'sale_ok': False,
    'purchase_ok': False, 'standard_price': 0, 'property_account_expense_id': account('625'),
    'taxes_id': [(6, 0, [])], 'supplier_taxes_id': [(6, 0, [])]})
bank_account = c.ensure('bank_account', 'account.account', {'name': 'TEST - Banca simulata',
    'code': '512190', 'account_type': 'asset_cash'})
incoming = c.ensure('outstanding_in', 'account.account', {'name': 'TEST - Incasari in curs',
    'code': '512191', 'account_type': 'asset_current', 'reconcile': True})
outgoing = c.ensure('outstanding_out', 'account.account', {'name': 'TEST - Plati in curs',
    'code': '512192', 'account_type': 'asset_current', 'reconcile': True})
bank = c.ensure('bank_journal', 'account.journal', {'name': 'Banca TEST - fara conexiune reala',
    'code': 'BTST', 'type': 'bank', 'default_account_id': bank_account})
methods = c.search('account.payment.method.line', [('journal_id', '=', bank)], ['payment_type'])
for method in methods:
    c.write('account.payment.method.line', method['id'], {
        'payment_account_id': incoming if method['payment_type'] == 'inbound' else outgoing})
    c.state['method_' + method['payment_type']] = method['id']
c.state['funding_account'] = account('4551')
c.state['travel_account'] = account('625')
c.save()
print('Scenario configuration complete; no messages or real payments sent.')

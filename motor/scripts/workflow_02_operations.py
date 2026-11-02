from datetime import date
import base64
from workflow_demo_client import Client

c = Client()
s = c.state
today = date.today().isoformat()
distribution = {str(s['analytic']): 100.0}
unit = c.read('product.product', s['panel'], ['uom_id'])['uom_id'][0]

stages = []
for key, name, sequence in [('stage_plan', '01 - Planificat', 1),
                            ('stage_work', '02 - In executie', 2),
                            ('stage_done', '03 - Finalizat', 3)]:
    stages.append(c.ensure(key, 'project.task.type', {'name': name, 'sequence': sequence,
        'project_ids': [(4, s['project'])], 'fold': key == 'stage_done'}))

sale = c.ensure('sale', 'sale.order', {'partner_id': s['customer'], 'project_id': s['project'],
    'client_order_ref': 'TEST-PV-001', 'note': '<p>DEMONSTRATIE FICTIVA - fara valoare comerciala. 10 panouri x 500 W si montaj la pret fix.</p>',
    'order_line': [(0, 0, {'product_id': s['panel'], 'name': 'TEST - 10 panouri fotovoltaice 500 W',
        'product_uom_qty': 10, 'product_uom_id': unit, 'price_unit': 600,
        'tax_ids': [(6, 0, [s['sale_tax']])], 'analytic_distribution': distribution}),
        (0, 0, {'product_id': s['service'], 'name': 'TEST - Montaj si punere in functiune 5 kW',
        'product_uom_qty': 1, 'price_unit': 1500, 'tax_ids': [(6, 0, [s['service_tax']])],
        'analytic_distribution': distribution})]})
if c.read('sale.order', sale, ['state'])['state'] in ('draft', 'sent'):
    c.call('sale.order', 'action_confirm', [[sale]])
print('Quotation accepted -> sales order confirmed', flush=True)
sale_lines = c.search('sale.order.line', [('order_id', '=', sale)], ['product_id', 'task_id'])
service_line = next(line for line in sale_lines if line['product_id'][0] == s['service'])
c.state['sale_service_line'] = service_line['id']
task = service_line['task_id'][0]
c.state['task_install'] = task
c.save()
c.write('project.task', task, {'name': '03 - Montaj si punere in functiune [TEST]',
    'stage_id': s['stage_work'], 'allocated_hours': 8.0, 'user_ids': [(6, 0, [c.uid])]})
c.write('project.project', s['project'], {'sale_line_id': service_line['id'], 'last_update_status': 'on_track'})
for key, name in [('task_plan', '01 - Planificare si necesar materiale [TEST]'),
                  ('task_receipt', '02 - Receptie si verificare materiale [TEST]'),
                  ('task_handover', '04 - Predare catre client si inchidere [TEST]')]:
    c.ensure(key, 'project.task', {'name': name, 'project_id': s['project'],
        'partner_id': s['customer'], 'stage_id': s['stage_plan'], 'user_ids': [(6, 0, [c.uid])]})
c.write('project.task', s['task_plan'], {'state': '1_done', 'stage_id': s['stage_done']})

purchase = c.ensure('purchase', 'purchase.order', {'partner_id': s['vendor'],
    'project_id': s['project'], 'origin': c.read('sale.order', sale, ['name'])['name'],
    'partner_ref': 'OFERTA-TEST-FURN-001', 'note': 'DATE FICTIVE - achizitie demonstrativa pentru proiectul TEST-PV-001.',
    'order_line': [(0, 0, {'product_id': s['panel'], 'name': 'TEST - Panouri fotovoltaice 500 W',
        'product_qty': 10, 'product_uom_id': unit, 'price_unit': 400,
        'date_planned': today + ' 08:00:00', 'tax_ids': [(6, 0, [s['purchase_tax']])],
        'analytic_distribution': distribution})]})
if c.read('purchase.order', purchase, ['state'])['state'] in ('draft', 'sent', 'to approve'):
    c.call('purchase.order', 'button_confirm', [[purchase]])
receipt = c.read('purchase.order', purchase, ['picking_ids'])['picking_ids'][0]
c.state['receipt'] = receipt
c.save()

def validate_picking(picking):
    values = c.read('stock.picking', picking, ['state', 'move_ids'])
    if values['state'] == 'done':
        return
    c.call('stock.picking', 'action_assign', [[picking]])
    for move in c.call('stock.move', 'read', [values['move_ids']], {'fields': ['product_uom_qty']}):
        c.write('stock.move', move['id'], {'quantity': move['product_uom_qty'], 'picked': True})
    result = c.call('stock.picking', 'button_validate', [[picking]])
    assert c.read('stock.picking', picking, ['state'])['state'] == 'done', result

validate_picking(receipt)
c.write('project.task', s['task_receipt'], {'state': '1_done', 'stage_id': s['stage_done']})
print('Purchase confirmed; 10 panels received into stock', flush=True)
bill_ids = c.read('purchase.order', purchase, ['invoice_ids'])['invoice_ids']
if not bill_ids:
    c.call('purchase.order', 'action_create_invoice', [[purchase]])
    bill_ids = c.read('purchase.order', purchase, ['invoice_ids'])['invoice_ids']
assert len(bill_ids) == 1
bill = bill_ids[0]
c.state['vendor_bill'] = bill
c.save()
if c.read('account.move', bill, ['state'])['state'] == 'draft':
    c.write('account.move', bill, {'invoice_date': today, 'ref': 'TEST-FURN-001'})
    c.call('account.move', 'action_post', [[bill]])
print('Supplier invoice posted:', c.read('account.move', bill, ['amount_untaxed', 'amount_tax', 'amount_total']), flush=True)

c.ensure('timesheet', 'account.analytic.line', {'name': 'TEST - Montaj 10 panouri si probe de functionare',
    'project_id': s['project'], 'task_id': task, 'employee_id': s['employee'],
    'date': today, 'unit_amount': 8.0, 'so_line': service_line['id']})
c.write('project.task', task, {'state': '1_done', 'stage_id': s['stage_done']})
delivery = c.read('sale.order', sale, ['picking_ids'])['picking_ids'][0]
c.state['delivery'] = delivery
c.save()
c.write('stock.picking', delivery, {'project_id': s['project']})
validate_picking(delivery)
print('8 hours recorded; installation complete; 10 panels delivered', flush=True)

expense = c.ensure('expense', 'hr.expense', {'name': 'TEST - Deplasare la santier, fara TVA dedusa',
    'employee_id': s['employee'], 'product_id': s['travel_product'], 'date': today,
    'quantity': 1, 'total_amount_currency': 200.0, 'payment_mode': 'own_account',
    'manager_id': c.uid, 'account_id': s['travel_account'], 'tax_ids': [(6, 0, [])],
    'analytic_distribution': distribution,
    'description': 'Cheltuiala fictiva pentru demonstratie. Suma 200 RON; TVA nu se deduce in acest scenariu.'})
receipt_text = ('DOCUMENT DEMONSTRATIV - FARA VALOARE FISCALA\n'
                'Deplasare la santier TEST-PV-001\nTotal fictiv: 200 RON\n'
                'Nu reprezinta un bon fiscal real.\n')
attachment = c.ensure('expense_receipt', 'ir.attachment', {'name': 'BON-DEMO-FARA-VALOARE-FISCALA.txt',
    'type': 'binary', 'datas': base64.b64encode(receipt_text.encode()).decode(),
    'mimetype': 'text/plain', 'res_model': 'hr.expense', 'res_id': expense})
c.write('hr.expense', expense, {'message_main_attachment_id': attachment})
state = c.read('hr.expense', expense, ['state'])['state']
if state == 'draft':
    c.call('hr.expense', 'action_submit', [[expense]])
if c.read('hr.expense', expense, ['state'])['state'] == 'submitted':
    c.call('hr.expense', 'action_approve', [[expense]])
if c.read('hr.expense', expense, ['state'])['state'] == 'approved':
    action = c.call('hr.expense', 'action_post', [[expense]])
    c.call('hr.expense.post.wizard', 'action_post_entry', [[action['res_id']]], context=action['context'])
c.state['expense_move'] = c.read('hr.expense', expense, ['account_move_id'])['account_move_id'][0]
c.save()
print('Expense submitted, approved and posted: 200 RON to reimburse', flush=True)

invoices = c.read('sale.order', sale, ['invoice_ids'])['invoice_ids']
if not invoices:
    wizard = c.call('sale.advance.payment.inv', 'create', [[{
        'advance_payment_method': 'delivered', 'sale_order_ids': [(6, 0, [sale])]}]],
        context={'active_model': 'sale.order', 'active_ids': [sale], 'active_id': sale})[0]
    c.call('sale.advance.payment.inv', 'create_invoices', [[wizard]])
    invoices = c.read('sale.order', sale, ['invoice_ids'])['invoice_ids']
assert len(invoices) == 1
invoice = invoices[0]
c.state['customer_invoice'] = invoice
c.save()
if c.read('account.move', invoice, ['state'])['state'] == 'draft':
    c.write('account.move', invoice, {'invoice_date': today, 'ref': 'TEST-PV-001',
        'narration': '<p>DOCUMENT DE TEST - FARA VALOARE FISCALA. Nu se transmite clientului sau ANAF.</p>'})
    c.call('account.move', 'action_post', [[invoice]])
print('Customer invoice posted:', c.read('account.move', invoice, ['amount_untaxed', 'amount_tax', 'amount_total']), flush=True)
print('Operational flow complete; bank settlement is next.', flush=True)

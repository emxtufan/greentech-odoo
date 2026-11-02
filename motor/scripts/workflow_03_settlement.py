from datetime import date
from workflow_demo_client import Client

c = Client()
s = c.state
today = date.today().isoformat()

def register_payment(key, move, direction, description):
    if key in c.state:
        return c.state[key]
    data = c.read('account.move', move, ['amount_residual', 'payment_state'])
    assert data['amount_residual'] > 0, 'Review existing payments before retrying'
    context = {'active_model': 'account.move', 'active_ids': [move], 'active_id': move}
    wizard = c.call('account.payment.register', 'create', [[{
        'journal_id': s['bank_journal'], 'payment_method_line_id': s['method_' + direction],
        'amount': data['amount_residual'], 'payment_date': today, 'communication': description,
    }]], context=context)[0]
    action = c.call('account.payment.register', 'action_create_payments', [[wizard]], context=context)
    payment = action['res_id']
    c.state[key] = payment
    c.save()
    print('Registered payment:', key, data['amount_residual'], flush=True)
    return payment

register_payment('payment_customer', s['customer_invoice'], 'inbound', 'TEST - Incasare client TEST-PV-001')
register_payment('payment_vendor', s['vendor_bill'], 'outbound', 'TEST - Plata furnizor TEST-FURN-001')
register_payment('payment_employee', s['expense_move'], 'outbound', 'TEST - Rambursare deplasare Alex')

statement = c.ensure('bank_statement', 'account.bank.statement', {
    'name': 'EXTRAS FICTIV TEST-PV-001 - fara operatiuni bancare reale',
    'balance_start': 0.0, 'balance_end_real': 14035.0})
c.ensure('bank_funding', 'account.bank.statement.line', {
    'statement_id': statement, 'journal_id': s['bank_journal'], 'date': today,
    'payment_ref': 'TEST - Finantare initiala fictiva de la asociat', 'amount': 10000.0,
    'counterpart_account_id': s['funding_account']})

def match_statement(key, payment_key, amount, partner, account):
    payment = c.read('account.payment', s[payment_key], ['move_id'])
    statement_line = c.ensure(key, 'account.bank.statement.line', {
        'statement_id': statement, 'journal_id': s['bank_journal'], 'date': today,
        'payment_ref': 'EXTRAS FICTIV - ' + payment_key,
        'partner_id': partner, 'amount': amount, 'counterpart_account_id': account})
    line = c.read('account.bank.statement.line', statement_line, ['move_id'])
    counterpart_lines = c.search('account.move.line', [
        ('move_id', 'in', [payment['move_id'][0], line['move_id'][0]]),
        ('account_id', '=', account), ('reconciled', '=', False)],
        ['balance', 'amount_residual'])
    if counterpart_lines:
        assert len(counterpart_lines) == 2
        assert abs(sum(row['balance'] for row in counterpart_lines)) < 0.005
        c.call('account.move.line', 'reconcile', [[row['id'] for row in counterpart_lines]])
    assert c.read('account.bank.statement.line', statement_line, ['is_reconciled'])['is_reconciled']
    print('Statement matched:', key, amount, flush=True)

employee_partner = c.read('hr.employee', s['employee'], ['work_contact_id'])['work_contact_id'][0]
match_statement('bank_customer', 'payment_customer', 9075.0, s['customer'], s['outstanding_in'])
match_statement('bank_vendor', 'payment_vendor', -4840.0, s['vendor'], s['outstanding_out'])
match_statement('bank_employee', 'payment_employee', -200.0, employee_partner, s['outstanding_out'])
c.write('account.bank.statement', statement, {'balance_end_real': 14035.0})

for key in ('customer_invoice', 'vendor_bill', 'expense_move'):
    values = c.read('account.move', s[key], ['name', 'payment_state', 'amount_residual'])
    print(key, values, flush=True)
    assert values['payment_state'] == 'paid' and values['amount_residual'] == 0
assert c.read('hr.expense', s['expense'], ['state'])['state'] == 'paid'
c.write('project.task', s['task_handover'], {'state': '1_done', 'stage_id': s['stage_done']})
c.write('project.project', s['project'], {'last_update_status': 'done'})
print('All invoices and expense paid; project completed.', flush=True)

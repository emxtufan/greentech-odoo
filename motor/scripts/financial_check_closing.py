"""Execute native month closing inside a transaction and roll it back afterwards.

Run with Odoo shell against greentech_financiar_test only. No closing entry is
retained, so the user can continue learning in the open demonstration month.
"""
import json
from pathlib import Path

root = Path.cwd()
assert env.cr.dbname == 'greentech_financiar_test'
state = json.loads((root / 'logs/financial-state.json').read_text(encoding='utf-8'))
env = env(context=dict(env.context, tracking_disable=True, mail_create_nosubscribe=True))
before = env['account.move'].search_count([])
try:
    for key in ['close_income', 'close_expense']:
        env['l10n.ro.account.period.closing'].browse(state[key]).close(
            date_from='2026-10-01', date_to='2026-10-31')
    env.flush_all()
    env.cr.execute("""SELECT COALESCE(SUM(l.balance),0) FROM account_move_line l
        JOIN account_move m ON m.id=l.move_id JOIN account_account a ON a.id=l.account_id
        WHERE m.state='posted' AND a.account_type IN
        ('income','income_other','expense','expense_other','expense_depreciation','expense_direct_cost')""")
    assert env.cr.fetchone()[0] == 0, 'P&L accounts did not close to zero'
    account = env['account.account'].search([('code','=like','121%')],limit=1)
    env.cr.execute("SELECT SUM(balance) FROM account_move_line WHERE account_id=%s AND parent_state='posted'", (account.id,))
    assert env.cr.fetchone()[0] == -5200, 'Wrong retained result'
    created = env['account.move'].search_count([]) - before
    assert created == 2
    result = {'native_closing_test': 'passed', 'new_closing_entries_in_transaction': created,
              'pnl_after_closing': 0, 'result_account_credit': 5200,
              'persisted': False, 'reason': 'Test transaction rolled back; demo month remains open.'}
finally:
    env.cr.rollback()
(root / 'logs/financial-closing-test.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('Native Romanian month closing passed; transaction rolled back.')

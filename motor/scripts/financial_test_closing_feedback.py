"""Odoo shell regression checks. Roll back every accounting change."""
import json
from pathlib import Path
from odoo.exceptions import UserError

assert env.cr.dbname == 'greentech_financiar_test'
results = {}
try:
    model = env['l10n.ro.account.period.closing']
    wizard_model = env['l10n.ro.account.period.closing.wizard']
    before = env['account.move'].search_count([])
    for label, start, end in [
        ('empty_september', '2026-09-01', '2026-09-30'),
        ('invalid_dates', '2026-10-31', '2026-10-01'),
    ]:
        wizard = wizard_model.create({'closing_id': 2, 'journal_id': 9, 'date_from': start, 'date_to': end})
        try:
            with env.cr.savepoint():
                wizard.do_close()
        except UserError as error:
            results[label] = str(error)
        else:
            raise AssertionError(label + ' unexpectedly accepted')
        assert env['account.move'].search_count([]) == before
    created = []
    for closing_id, expected in [(1, 21750), (2, 16550)]:
        wizard = wizard_model.create({'closing_id': closing_id, 'journal_id': 9,
                                     'date_from': '2026-10-01', 'date_to': '2026-10-31'})
        action = wizard.do_close()
        assert action['res_model'] == 'account.move' and action['view_mode'] == 'form'
        move = env['account.move'].browse(action['res_id'])
        assert move.state == 'posted'
        assert sum(move.line_ids.mapped('debit')) == expected
        assert sum(move.line_ids.mapped('balance')) == 0
        created.append(move.id)
        try:
            with env.cr.savepoint():
                wizard.do_close()
        except UserError:
            results['repeat_' + str(closing_id)] = 'blocked without duplicate'
        else:
            raise AssertionError('Repeat closing accepted')
    env.flush_all()
    result_lines = env['account.move.line'].search([
        ('move_id', 'in', created), ('account_id.code', '=like', '121%')])
    assert sum(result_lines.mapped('balance')) == -5200
    assert env['account.move'].search_count([]) == before + 2
    results.update(success=True, result_credit=5200, returned_posted_entries=2, persisted=False)
finally:
    env.cr.rollback()
Path('logs/closing-feedback-test.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('Closing feedback verified: visible posted entries, empty/repeat/invalid dates blocked; all test postings rolled back.')

from odoo import fields, models
from odoo.exceptions import UserError


class PeriodClosing(models.Model):
    _inherit = 'l10n.ro.account.period.closing'

    def close(self, journal_id=None, date_from=None, date_to=None):
        start, end = fields.Date.to_date(date_from), fields.Date.to_date(date_to)
        if not start or not end or start > end:
            raise UserError('Selectați o perioadă validă: data de început trebuie să fie înaintea datei de sfârșit sau egală cu aceasta.')
        moves = self.env['account.move']
        for closing in self:
            # Serialize clicks on the same model before checking remaining balances.
            self.env.cr.execute('SELECT id FROM l10n_ro_account_period_closing WHERE id = %s FOR UPDATE', [closing.id])
            balances = closing.with_context(
                strict_range=True, state='posted', date_from=start, date_to=end,
                company_id=closing.company_id.id,
            )._get_accounts(closing.account_ids, 'not_zero')
            if not balances:
                raise UserError(
                    'Nu există solduri de închis pentru „%s” în perioada %s – %s. '
                    'Verificați perioada și documentele validate; conturile pot fi deja închise. '
                    'Nu a fost creată nicio notă contabilă.'
                    % (closing.name, start.strftime('%d.%m.%Y'), end.strftime('%d.%m.%Y'))
                )
            before = self.env['account.move'].search([('l10n_ro_close_id', '=', closing.id)])
            super(PeriodClosing, closing).close(journal_id=journal_id, date_from=start, date_to=end)
            moves |= self.env['account.move'].search([('l10n_ro_close_id', '=', closing.id)]) - before
        return moves


class ClosingWizard(models.TransientModel):
    _inherit = 'l10n.ro.account.period.closing.wizard'

    def do_close(self):
        moves = self.env['account.move']
        for wizard in self:
            moves |= wizard.closing_id.close(wizard.journal_id.id, wizard.date_from, wizard.date_to)
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Note contabile de închidere generate',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', moves.ids)],
            'target': 'current',
        }
        if len(moves) == 1:
            action.update(view_mode='form', res_id=moves.id)
        return action

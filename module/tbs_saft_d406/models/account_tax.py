# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Link Odoo taxes to the ANAF SAF-T tax nomenclatures."""
from odoo import _, api, fields, models


class AccountTax(models.Model):
    _inherit = 'account.tax'

    l10n_ro_d406_tax_type_id = fields.Many2one(
        comodel_name='l10n.ro.d406.tax.type',
        string='SAF-T Tax Type',
        ondelete='restrict',
        help='ANAF levy code reported as <TaxType>. For VAT this is the '
             'VAT entry of the ANAF tax nomenclature.',
    )
    l10n_ro_d406_tax_code_id = fields.Many2one(
        comodel_name='l10n.ro.d406.tax.code',
        string='SAF-T Tax Code',
        ondelete='restrict',
        help='Six-digit ANAF VAT code reported as <TaxCode>. This is the '
             'field that determines which D300/D394 line the transaction '
             'lands on, so it must match the nature of the supply, not just '
             'the rate.',
    )
    l10n_ro_d406_tax_code_display = fields.Char(
        string='SAF-T Code',
        compute='_compute_l10n_ro_d406_tax_code_display',
    )

    @api.depends('l10n_ro_d406_tax_type_id.code', 'l10n_ro_d406_tax_code_id.code')
    def _compute_l10n_ro_d406_tax_code_display(self):
        for tax in self:
            parts = [
                tax.l10n_ro_d406_tax_type_id.code,
                tax.l10n_ro_d406_tax_code_id.code,
            ]
            tax.l10n_ro_d406_tax_code_display = ' / '.join(p for p in parts if p)

    @api.model
    def l10n_ro_d406_unmapped_taxes(self):
        """Active taxes with no SAF-T code, which block a valid export."""
        return self.search([
            ('company_id', 'in', self.env.companies.ids),
            '|',
            ('l10n_ro_d406_tax_type_id', '=', False),
            ('l10n_ro_d406_tax_code_id', '=', False),
        ])

    def action_l10n_ro_d406_open_unmapped(self):
        unmapped = self.l10n_ro_d406_unmapped_taxes()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Taxes without a SAF-T code'),
            'res_model': 'account.tax',
            'view_mode': 'list,form',
            'domain': [('id', 'in', unmapped.ids)],
        }

# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Invoice-level D406 attributes."""
from odoo import api, fields, models

#: SAF-T ``InvoiceType`` values for the document kinds Odoo produces.
#: 380 = commercial invoice, 381 = credit note, 389 = self-billed invoice
#: (autofactura). Taken from workbook sheet ``Nom_Tipuri_facturi``.
INVOICE_TYPE_STANDARD = '380'
INVOICE_TYPE_CREDIT_NOTE = '381'
INVOICE_TYPE_SELF_BILLED = '389'


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_ro_d406_is_self_invoice = fields.Boolean(
        string='Self-billed (autofactura)',
        help='Marks the document as a self-billed invoice. Reported as '
             'InvoiceType 389 and sets SelfBillingIndicator on the partner.',
    )
    l10n_ro_d406_invoice_type = fields.Char(
        string='SAF-T Invoice Type',
        compute='_compute_l10n_ro_d406_invoice_type',
        help='Value reported as <InvoiceType> in the D406 declaration.',
    )

    @api.depends('move_type', 'l10n_ro_d406_is_self_invoice')
    def _compute_l10n_ro_d406_invoice_type(self):
        for move in self:
            move.l10n_ro_d406_invoice_type = move._l10n_ro_d406_invoice_type()

    def _l10n_ro_d406_invoice_type(self):
        """Return the SAF-T InvoiceType for this document."""
        self.ensure_one()
        if self.l10n_ro_d406_is_self_invoice:
            return INVOICE_TYPE_SELF_BILLED
        if self.move_type in ('out_refund', 'in_refund'):
            return INVOICE_TYPE_CREDIT_NOTE
        return INVOICE_TYPE_STANDARD

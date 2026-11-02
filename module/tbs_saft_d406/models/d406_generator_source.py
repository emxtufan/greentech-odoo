# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""``SourceDocuments`` — sales invoices, purchase invoices and payments.

``MovementOfGoods`` is a mandatory container that stays empty here: it
belongs to the on-demand (C) declaration, which needs stock data and is
planned as a separate module. An empty container is schema-valid; emitting
*content* for it in a periodic declaration is what DUKIntegrator rejects.
"""
from odoo import _, api, models
from odoo.exceptions import UserError

from ..d406 import sanitize
from ..d406.xmlbuilder import Node

#: Journal item selection for the Payments section: money actually moving.
PAYMENT_JOURNAL_TYPES = ('bank', 'cash')

#: ``SelfBillingIndicator`` is mandatory on every invoice: 1 when the
#: document was issued by the customer on the supplier's behalf, else 0.
SELF_BILLING_YES = '1'
SELF_BILLING_NO = '0'

#: ANAF ``PaymentMethod`` codes. The nomenclature collapses 83 payment
#: *mechanisms* onto five *methods*; it is the method code that goes in the
#: XML. Using a mechanism code here (10 for cash, 42 for bank transfer) is a
#: natural mistake and produces an invalid file.
PAYMENT_METHOD_CASH = '01'
PAYMENT_METHOD_NON_CASH = '03'
DEFAULT_PAYMENT_METHOD = '99'  # Instrument not defined


class D406GeneratorSource(models.AbstractModel):
    _inherit = 'l10n.ro.d406.generator'

    @api.model
    def _build_source_documents(self, parent: Node, context):
        self._build_sales_invoices(parent.child('SalesInvoices'), context)
        self._build_purchase_invoices(parent.child('PurchaseInvoices'), context)
        self._build_payments(parent.child('Payments'), context)
        # Mandatory container, intentionally empty for L/T/NL/NT.
        parent.child('MovementOfGoods')

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    @api.model
    def _invoice_moves(self, context, move_types):
        return self.env['account.move'].search([
            ('company_id', '=', context['company'].id),
            ('state', '=', 'posted'),
            ('move_type', 'in', move_types),
            ('date', '>=', context['date_from']),
            ('date', '<=', context['date_to']),
        ], order='name, id')

    @api.model
    def _build_sales_invoices(self, parent: Node, context):
        moves = self._invoice_moves(context, ('out_invoice', 'out_refund'))
        self._add_document_header_totals(parent, moves, context)
        for move in moves:
            self._build_invoice(parent, move, context, is_sale=True)

    @api.model
    def _build_purchase_invoices(self, parent: Node, context):
        moves = self._invoice_moves(context, ('in_invoice', 'in_refund'))
        self._add_document_header_totals(parent, moves, context)
        for move in moves:
            self._build_invoice(parent, move, context, is_sale=False)

    @api.model
    def _add_document_header_totals(self, parent: Node, moves, context):
        """``NumberOfEntries`` / ``TotalDebit`` / ``TotalCredit``."""
        debit = sum(moves.mapped('line_ids').mapped('debit'))
        credit = sum(moves.mapped('line_ids').mapped('credit'))
        parent.add_required('NumberOfEntries', str(len(moves)))
        parent.add_required('TotalDebit', sanitize.monetary(debit))
        parent.add_required('TotalCredit', sanitize.monetary(credit))

    @api.model
    def _build_invoice(self, parent: Node, move, context, is_sale=True):
        node = parent.child('Invoice')
        node.add_required('InvoiceNo', sanitize.text(move.name, 70))
        self._add_invoice_party(node, move, context, is_sale=is_sale)
        node.add_required('AccountID', self._invoice_account_id(move))
        node.add('Period', str(move.date.month))
        node.add('PeriodYear', str(move.date.year))
        node.add_required('InvoiceDate', move.invoice_date.isoformat()
                          if move.invoice_date else move.date.isoformat())
        node.add_required('InvoiceType', move._l10n_ro_d406_invoice_type())
        node.add('PaymentTerms',
                 sanitize.text(move.invoice_payment_term_id.name, 200))
        node.add_required(
            'SelfBillingIndicator',
            SELF_BILLING_YES if move.l10n_ro_d406_is_self_invoice
            else SELF_BILLING_NO)
        node.add('SourceID', sanitize.text(
            move.invoice_user_id.name or move.create_uid.name, 35))
        node.add('GLPostingDate', move.date.isoformat())
        node.add('TransactionID', sanitize.text(move.name, 70))

        for index, line in enumerate(self._invoice_product_lines(move), start=1):
            self._build_invoice_line(node, line, index, context)

        self._add_invoice_totals(node, move, context)

    @api.model
    def _add_invoice_party(self, parent: Node, move, context, is_sale=True):
        """``CustomerInfo`` or ``SupplierInfo`` — a mandatory choice."""
        partner = move.partner_id.commercial_partner_id or move.partner_id
        node = parent.child('CustomerInfo' if is_sale else 'SupplierInfo')
        node.add_required(
            'CustomerID' if is_sale else 'SupplierID',
            self._partner_saft_id(partner, context, is_customer=is_sale))
        if not self._add_address(node, partner, tag='BillingAddress'):
            # BillingAddress is mandatory inside the party block. Fall back to
            # the company's own address rather than emitting a partial one,
            # and record it so the accountant can fix the partner record.
            self._add_address(node, context['company'].partner_id,
                              tag='BillingAddress')
            context['warnings'].append(
                f'Invoice {move.name}: partner "{partner.display_name}" has no '
                f'usable address; the company address was used instead.')

    @api.model
    def _invoice_account_id(self, move):
        """The receivable/payable account the invoice is booked against."""
        target_types = ('asset_receivable', 'liability_payable')
        for line in move.line_ids:
            if line.account_id.account_type in target_types:
                return sanitize.account_id(line.account_id.code)
        return sanitize.account_id(
            move.line_ids[:1].account_id.code) if move.line_ids else '0'

    @api.model
    def _invoice_product_lines(self, move):
        """Billable lines only — no tax, section or note lines."""
        return move.invoice_line_ids.filtered(
            lambda l: l.display_type in (False, 'product'))

    @api.model
    def _build_invoice_line(self, parent: Node, line, index, context):
        node = parent.child('InvoiceLine')
        node.add('LineNumber', str(index))
        node.add_required(
            'AccountID', sanitize.account_id(line.account_id.code) or '0')
        node.add('ProductCode', sanitize.text(
            line.product_id.default_code or
            (str(line.product_id.id) if line.product_id else ''), 70))
        node.add('ProductDescription',
                 sanitize.text(line.product_id.name, 256))
        node.add_required('Quantity', sanitize.quantity(line.quantity))
        node.add('InvoiceUOM', self._uom_code(line.product_uom_id))
        node.add_required('UnitPrice', sanitize.monetary(line.price_unit))
        node.add_required(
            'TaxPointDate',
            (line.move_id.invoice_date or line.move_id.date).isoformat())
        node.add_required(
            'Description',
            sanitize.text(line.name or line.product_id.name, 256))
        self._add_amount(node, 'InvoiceLineAmount',
                         abs(line.balance), context)
        # D when the line increases a debit balance (customer invoice), C
        # otherwise. Refunds flip the sign, which balance already reflects.
        node.add_required(
            'DebitCreditIndicator', 'D' if line.balance >= 0 else 'C')
        self._add_tax_information(node, line, context)

    @api.model
    def _add_invoice_totals(self, parent: Node, move, context):
        """``InvoiceDocumentTotals`` — net and gross must tie to the move.

        Schema order matters: every ``TaxInformationTotals`` block comes
        first, then ``NetTotal``, then ``GrossTotal``.
        """
        node = parent.child('InvoiceDocumentTotals')
        for tax, base, amount in self._invoice_tax_totals(move):
            block = node.child('TaxInformationTotals')
            block.add_required('TaxType', tax.l10n_ro_d406_tax_type_id.code)
            block.add_required('TaxCode', tax.l10n_ro_d406_tax_code_id.code)
            block.add('TaxPercentage', sanitize.monetary(tax.amount))
            block.add('TaxBase', sanitize.monetary(base))
            self._add_amount(block, 'TaxAmount', amount, context)
        node.add_required(
            'NetTotal', sanitize.monetary(abs(move.amount_untaxed)))
        node.add_required(
            'GrossTotal', sanitize.monetary(abs(move.amount_total)))

    @api.model
    def _invoice_tax_totals(self, move):
        """Yield ``(tax, base, amount)`` per mapped tax used on the invoice."""
        by_tax = {}
        for line in self._invoice_product_lines(move):
            for tax in line.tax_ids:
                if not (tax.l10n_ro_d406_tax_type_id
                        and tax.l10n_ro_d406_tax_code_id):
                    continue
                base, amount = by_tax.get(tax, (0.0, 0.0))
                by_tax[tax] = (
                    base + abs(line.balance),
                    amount + self._line_tax_amount(line, tax),
                )
        return [(tax, base, amount)
                for tax, (base, amount) in by_tax.items()]

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    @api.model
    def _build_payments(self, parent: Node, context):
        """``Payments`` — at least one entry, or no file at all.

        The XSD allows ``0..unbounded`` ``Payment`` entries, but
        DUKIntegrator requires at least one in a periodic declaration and
        rejects a file whose ``Payments`` section is empty. A period with no
        bank or cash movement therefore has no valid representation, so this
        fails with a named cause rather than writing a file that comes back
        from DUK as an unexplained rejection -- the same reasoning as
        ``add_required`` raising instead of emitting an empty element.
        """
        moves = self._payment_moves(context)
        if not moves:
            raise UserError(_(
                'No bank or cash journal entries were found between '
                '%(date_from)s and %(date_to)s, so the Payments section '
                'would be empty. DUKIntegrator requires at least one '
                'payment in a periodic declaration and rejects the file '
                'otherwise.\n\n'
                'Check that the period is correct, that the bank and cash '
                'journal entries for it are posted, and that they belong to '
                'company %(company)s.',
                date_from=context['date_from'],
                date_to=context['date_to'],
                company=context['company'].display_name,
            ))
        self._add_document_header_totals(parent, moves, context)
        for move in moves:
            self._build_payment(parent, move, context)

    @api.model
    def _payment_moves(self, context):
        """Bank and cash journal entries in the period.

        Sourced from journal entries rather than ``account.payment`` so that
        bank statement lines reconciled without a payment record — the
        majority on an imported statement — are still reported.
        """
        return self.env['account.move'].search([
            ('company_id', '=', context['company'].id),
            ('state', '=', 'posted'),
            ('journal_id.type', 'in', PAYMENT_JOURNAL_TYPES),
            ('date', '>=', context['date_from']),
            ('date', '<=', context['date_to']),
        ], order='name, id')

    @api.model
    def _build_payment(self, parent: Node, move, context):
        node = parent.child('Payment')
        node.add_required('PaymentRefNo', sanitize.text(move.name, 70))
        node.add('Period', str(move.date.month))
        node.add('PeriodYear', str(move.date.year))
        node.add('TransactionID', sanitize.text(move.name, 70))
        node.add_required('TransactionDate', move.date.isoformat())
        node.add_required('PaymentMethod', self._payment_method(move))
        node.add_required(
            'Description', sanitize.text(move.ref or move.name, 256))
        node.add('SourceID', sanitize.text(move.create_uid.name, 35))

        for index, line in enumerate(move.line_ids, start=1):
            self._build_payment_line(node, line, index, context)

        totals = node.child('PaymentDocumentTotals')
        gross = sum(abs(line.balance) for line in move.line_ids) / 2.0
        totals.add_required('GrossTotal', sanitize.monetary(gross))

    @api.model
    def _payment_method(self, move):
        """Map the journal onto an ANAF payment method code."""
        journal_type = move.journal_id.type
        if journal_type == 'cash':
            return PAYMENT_METHOD_CASH
        if journal_type == 'bank':
            return PAYMENT_METHOD_NON_CASH
        return DEFAULT_PAYMENT_METHOD

    @api.model
    def _build_payment_line(self, parent: Node, line, index, context):
        node = parent.child('PaymentLine')
        node.add('LineNumber', str(index))
        node.add('SourceDocumentID', sanitize.text(line.move_id.name, 35))
        node.add_required(
            'AccountID', sanitize.account_id(line.account_id.code) or '0')
        partner = line.partner_id or line.move_id.partner_id
        node.add_required(
            'CustomerID',
            self._partner_saft_id(partner, context, is_customer=True))
        node.add_required(
            'SupplierID',
            self._partner_saft_id(partner, context, is_customer=False))
        node.add('Description', sanitize.text(line.name, 256))
        node.add_required(
            'DebitCreditIndicator', 'D' if line.balance >= 0 else 'C')
        self._add_amount(node, 'PaymentLineAmount',
                         abs(line.balance), context)
        self._add_tax_information(node, line, context)

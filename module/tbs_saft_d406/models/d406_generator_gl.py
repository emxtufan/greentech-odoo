# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Ledger aggregation and the ``GeneralLedgerEntries`` section.

Odoo Enterprise gets these numbers from ``account_reports``, which does not
exist in Community. Everything here is therefore computed directly from
``account_move_line`` with plain SQL — deliberately, because the aggregate
has to tie out to the Romanian trial balance and a hand-written query is far
easier to reconcile than a report engine's option stack.

Opening balances follow Romanian trial-balance semantics: balance-sheet
accounts carry their full history forward, profit-and-loss accounts restart
at the fiscal year boundary.
"""
from odoo import _, api, models
from odoo.exceptions import UserError

from ..d406 import sanitize
from ..d406.xmlbuilder import Node

#: Odoo account types whose balance restarts each fiscal year.
PROFIT_AND_LOSS_TYPES = (
    'income', 'income_other',
    'expense', 'expense_depreciation', 'expense_direct_cost',
)

#: ANAF placeholder codes for a journal line that carries no tax.
#: ``TaxType 000`` is defined in the workbook as the code used only for the
#: specific cases where no levy applies; ``TaxCode 000000`` is its VAT
#: counterpart. Every ``TransactionLine`` needs a ``TaxInformation`` child.
NEUTRAL_TAX_TYPE = '000'
NEUTRAL_TAX_CODE = '000000'


class D406GeneratorGL(models.AbstractModel):
    _inherit = 'l10n.ro.d406.generator'

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    @api.model
    def _move_line_domain_sql(self, context):
        """Shared SQL predicate for posted lines of the reporting company."""
        return {
            'company_id': context['company'].id,
            'date_from': context['date_from'],
            'date_to': context['date_to'],
            'fy_start': context['fiscal_year_start'],
            'pl_types': PROFIT_AND_LOSS_TYPES,
        }

    @api.model
    def _account_balances(self, context):
        """Return ``{account_id: (opening_balance, closing_balance)}``.

        Only accounts that have either a non-zero balance or movement in the
        period are returned; reporting the entire chart including untouched
        accounts bloats the file without adding information.
        """
        params = self._move_line_domain_sql(context)
        self.env['account.move.line'].flush_model()
        self.env.cr.execute("""
            SELECT aml.account_id,
                   SUM(CASE
                         WHEN aml.date < %(date_from)s
                              AND (aa.account_type NOT IN %(pl_types)s
                                   OR aml.date >= %(fy_start)s)
                         THEN aml.balance ELSE 0 END) AS opening,
                   SUM(CASE
                         WHEN aml.date <= %(date_to)s
                              AND (aa.account_type NOT IN %(pl_types)s
                                   OR aml.date >= %(fy_start)s)
                         THEN aml.balance ELSE 0 END) AS closing,
                   SUM(CASE
                         WHEN aml.date BETWEEN %(date_from)s AND %(date_to)s
                         THEN 1 ELSE 0 END) AS moved
              FROM account_move_line aml
              JOIN account_move am ON am.id = aml.move_id
              JOIN account_account aa ON aa.id = aml.account_id
             WHERE aml.company_id = %(company_id)s
               AND am.state = 'posted'
               AND aml.date <= %(date_to)s
          GROUP BY aml.account_id
        """, params)

        balances = {}
        for account_id, opening, closing, moved in self.env.cr.fetchall():
            if not moved and not opening and not closing:
                continue
            balances[account_id] = (opening or 0.0, closing or 0.0)
        return balances

    @api.model
    def _partner_balances(self, context, receivable=True):
        """Yield ``(partner, opening, closing, account_code)`` per partner.

        SAF-T splits partners into customers and suppliers by the nature of
        the account their balance sits on, not by a flag on the partner, so
        the same company can legitimately appear in both sections.
        """
        params = self._move_line_domain_sql(context)
        params['account_type'] = (
            'asset_receivable' if receivable else 'liability_payable')
        self.env['account.move.line'].flush_model()
        self.env.cr.execute("""
            SELECT aml.partner_id,
                   MIN(aml.account_id) AS account_id,
                   SUM(CASE WHEN aml.date < %(date_from)s
                            THEN aml.balance ELSE 0 END) AS opening,
                   SUM(CASE WHEN aml.date <= %(date_to)s
                            THEN aml.balance ELSE 0 END) AS closing
              FROM account_move_line aml
              JOIN account_move am ON am.id = aml.move_id
              JOIN account_account aa ON aa.id = aml.account_id
             WHERE aml.company_id = %(company_id)s
               AND am.state = 'posted'
               AND aml.date <= %(date_to)s
               AND aml.partner_id IS NOT NULL
               AND aa.account_type = %(account_type)s
          GROUP BY aml.partner_id
          ORDER BY aml.partner_id
        """, params)

        rows = self.env.cr.fetchall()
        partners = self.env['res.partner'].browse(
            [row[0] for row in rows])
        accounts = self.env['account.account'].browse(
            [row[1] for row in rows])
        by_id = {account.id: account for account in accounts}

        results = []
        for (partner_id, account_id, opening, closing), partner in zip(
                rows, partners):
            account = by_id.get(account_id)
            code = sanitize.account_id(account.code) if account else ''
            results.append((partner, opening or 0.0, closing or 0.0, code))
        return results

    @api.model
    def _period_taxes(self, context):
        """Taxes actually applied on posted lines in the period."""
        params = self._move_line_domain_sql(context)
        self.env.cr.execute("""
            SELECT DISTINCT rel.account_tax_id
              FROM account_move_line_account_tax_rel rel
              JOIN account_move_line aml ON aml.id = rel.account_move_line_id
              JOIN account_move am ON am.id = aml.move_id
             WHERE aml.company_id = %(company_id)s
               AND am.state = 'posted'
               AND aml.date BETWEEN %(date_from)s AND %(date_to)s
        """, params)
        tax_ids = [row[0] for row in self.env.cr.fetchall()]
        return self.env['account.tax'].browse(tax_ids)

    @api.model
    def _period_products(self, context):
        """Products appearing on posted lines in the period."""
        params = self._move_line_domain_sql(context)
        self.env.cr.execute("""
            SELECT DISTINCT aml.product_id
              FROM account_move_line aml
              JOIN account_move am ON am.id = aml.move_id
             WHERE aml.company_id = %(company_id)s
               AND am.state = 'posted'
               AND aml.date BETWEEN %(date_from)s AND %(date_to)s
               AND aml.product_id IS NOT NULL
        """, params)
        product_ids = [row[0] for row in self.env.cr.fetchall()]
        return self.env['product.product'].browse(product_ids)

    @api.model
    def _period_uom_codes(self, context):
        """UN/ECE unit codes referenced by the products in the period."""
        codes = {self._uom_code(product.uom_id)
                 for product in self._period_products(context)}
        codes.discard('')
        # C62 (one/piece) is the fallback for anything unmapped, so it is
        # always declared even when no product explicitly uses it.
        codes.add('C62')
        return codes

    # ------------------------------------------------------------------
    # GeneralLedgerEntries
    # ------------------------------------------------------------------

    @api.model
    def _build_general_ledger_entries(self, parent: Node, context):
        moves = self._period_moves(context)
        totals = self._ledger_totals(context)

        parent.add_required('NumberOfEntries', str(len(moves)))
        parent.add_required('TotalDebit', sanitize.monetary(totals['debit']))
        parent.add_required('TotalCredit', sanitize.monetary(totals['credit']))

        for journal, journal_moves in self._group_by_journal(moves):
            node = parent.child('Journal')
            node.add_required('JournalID', sanitize.text(journal.code, 18))
            node.add_required('Description', sanitize.text(journal.name, 256))
            node.add_required('Type', sanitize.text(journal.type, 9))
            for move in journal_moves:
                self._build_transaction(node, move, context)

    @api.model
    def _period_moves(self, context):
        """Posted moves in the period, ordered for a stable file."""
        return self.env['account.move'].search([
            ('company_id', '=', context['company'].id),
            ('state', '=', 'posted'),
            ('date', '>=', context['date_from']),
            ('date', '<=', context['date_to']),
        ], order='journal_id, date, name, id')

    @api.model
    def _ledger_totals(self, context):
        """Period debit and credit totals.

        These must tie out to the trial balance; the export wizard surfaces
        them so the accountant can check the file before submitting it.
        """
        params = self._move_line_domain_sql(context)
        self.env['account.move.line'].flush_model()
        self.env.cr.execute("""
            SELECT COALESCE(SUM(aml.debit), 0), COALESCE(SUM(aml.credit), 0)
              FROM account_move_line aml
              JOIN account_move am ON am.id = aml.move_id
             WHERE aml.company_id = %(company_id)s
               AND am.state = 'posted'
               AND aml.date BETWEEN %(date_from)s AND %(date_to)s
        """, params)
        debit, credit = self.env.cr.fetchone()
        return {'debit': debit, 'credit': credit}

    @api.model
    def _group_by_journal(self, moves):
        """Group an ordered move recordset by journal, preserving order."""
        grouped = []
        current_journal = None
        bucket = None
        for move in moves:
            if move.journal_id != current_journal:
                current_journal = move.journal_id
                bucket = []
                grouped.append((current_journal, bucket))
            bucket.append(move)
        # A Journal with no Transaction child is invalid (minOccurs=1), and
        # the grouping above can never produce one, but guard anyway.
        return [(journal, bucket) for journal, bucket in grouped if bucket]

    @api.model
    def _build_transaction(self, parent: Node, move, context):
        node = parent.child('Transaction')
        node.add_required('TransactionID', sanitize.text(move.name, 70))
        node.add_required('Period', str(move.date.month))
        node.add_required('PeriodYear', str(move.date.year))
        node.add_required('TransactionDate', move.date.isoformat())
        node.add('SourceID', sanitize.text(
            move.invoice_user_id.name or move.create_uid.name, 35))
        node.add_required(
            'Description',
            sanitize.text(move.ref or move.name, 256))
        node.add_required(
            'SystemEntryDate',
            (move.create_date.date() if move.create_date else move.date).isoformat())
        node.add_required('GLPostingDate', move.date.isoformat())

        partner_id = self._partner_saft_id(
            move.partner_id, context, is_customer=True)
        supplier_id = self._partner_saft_id(
            move.partner_id, context, is_customer=False)
        node.add_required('CustomerID', partner_id)
        node.add_required('SupplierID', supplier_id)

        for line in move.line_ids:
            self._build_transaction_line(node, line, context)

    @api.model
    def _build_transaction_line(self, parent: Node, line, context):
        node = parent.child('TransactionLine')
        node.add_required('RecordID', str(line.id))
        account_code = sanitize.account_id(line.account_id.code)
        if not account_code:
            raise UserError(_(
                'Journal item %(line)s posts to account "%(account)s", whose '
                'code is not numeric. SAF-T <AccountID> must be an integer.',
                line=line.display_name, account=line.account_id.display_name,
            ))
        node.add_required('AccountID', account_code)
        node.add('SourceDocumentID', sanitize.text(line.move_id.name, 35))
        node.add_required(
            'CustomerID',
            self._partner_saft_id(line.partner_id or line.move_id.partner_id,
                                  context, is_customer=True))
        node.add_required(
            'SupplierID',
            self._partner_saft_id(line.partner_id or line.move_id.partner_id,
                                  context, is_customer=False))
        node.add_required(
            'Description',
            sanitize.text(line.name or line.move_id.name, 256))
        self._add_line_amount(node, line, context)
        self._add_tax_information(node, line, context)

    @api.model
    def _add_amount(self, parent: Node, tag, amount, context,
                    currency=None, currency_amount=None, rate=None):
        """Append an ``AmountStructure``.

        ``CurrencyCode`` and ``CurrencyAmount`` are both mandatory in the
        schema even when the transaction is in the company currency, so they
        are always emitted rather than guarded.
        """
        company_currency = context['company'].currency_id
        currency = currency or company_currency
        if currency_amount is None:
            currency_amount = amount
        node = parent.child(tag)
        node.add_required('Amount', sanitize.monetary(amount))
        node.add_required('CurrencyCode', currency.name or 'RON')
        node.add_required('CurrencyAmount', sanitize.monetary(currency_amount))
        node.add('ExchangeRate', f'{(rate if rate is not None else 1.0):.4f}')
        return node

    @api.model
    def _add_line_amount(self, parent: Node, line, context):
        """Append the ``DebitAmount``/``CreditAmount`` choice."""
        company_currency = context['company'].currency_id
        amount = abs(line.balance)
        currency = line.currency_id or company_currency
        if currency != company_currency:
            currency_amount = abs(line.amount_currency)
            rate = (currency_amount / amount) if amount else 1.0
        else:
            currency_amount, rate = amount, 1.0
        tag = 'DebitAmount' if line.balance >= 0 else 'CreditAmount'
        self._add_amount(parent, tag, amount, context,
                         currency=currency, currency_amount=currency_amount,
                         rate=rate)

    @api.model
    def _add_tax_information(self, parent: Node, line, context):
        """Append ``TaxInformation``, which is mandatory on every line.

        Lines carrying no mapped tax still need an entry, so a neutral one is
        emitted with ANAF's placeholder codes (``TaxType 000`` /
        ``TaxCode 000000``). Omitting the block fails the schema's
        ``minOccurs=1``; the placeholder is the form ANAF accepted on the
        reference file.
        """
        taxes = line.tax_ids.filtered(
            lambda t: t.l10n_ro_d406_tax_type_id and t.l10n_ro_d406_tax_code_id)
        if not taxes:
            node = parent.child('TaxInformation')
            node.add_required('TaxType', NEUTRAL_TAX_TYPE)
            node.add_required('TaxCode', NEUTRAL_TAX_CODE)
            self._add_amount(node, 'TaxAmount', 0.0, context)
            return

        for tax in taxes:
            node = parent.child('TaxInformation')
            node.add_required('TaxType', tax.l10n_ro_d406_tax_type_id.code)
            node.add_required('TaxCode', tax.l10n_ro_d406_tax_code_id.code)
            node.add('TaxPercentage', sanitize.monetary(tax.amount))
            node.add('TaxBase', sanitize.monetary(abs(line.balance)))
            self._add_amount(node, 'TaxAmount',
                             self._line_tax_amount(line, tax), context)

    @api.model
    def _line_tax_amount(self, line, tax):
        """Tax amount attributable to a base line for one tax.

        A tax line carries the amount directly on its balance; a base line
        has the tax computed off it. Odoo keeps the two in separate journal
        items, so the base line reports the computed figure.
        """
        if line.tax_line_id and line.tax_line_id == tax:
            return abs(line.balance)
        if tax.amount_type == 'percent':
            return abs(line.balance) * tax.amount / 100.0
        return 0.0

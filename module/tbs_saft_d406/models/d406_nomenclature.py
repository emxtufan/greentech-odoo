# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""ANAF nomenclatures used by the D406 SAF-T declaration.

These models are pure reference data. Every row is generated from the
official ANAF workbook by ``tools/generate_nomenclature.py`` and shipped as
CSV under ``data/nomenclature/``, so refreshing a nomenclature after ANAF
republishes it is a module upgrade, not a data migration.

The records are ``noupdate=False`` on purpose: an upgrade must be able to
correct a code whose description or validity dates changed.
"""
from odoo import api, fields, models


class D406TaxType(models.Model):
    """ANAF tax/levy nomenclature — SAF-T ``TaxType`` (3 characters).

    Source: workbook sheet ``TAX-IMP - Impozite``.
    """
    _name = 'l10n.ro.d406.tax.type'
    _description = 'D406 SAF-T Tax Type (ANAF)'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True, translate=False)
    name_en = fields.Char(string='Name (EN)')
    budget_category = fields.Char(
        help='ANAF budget category the levy is collected under.')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The ANAF tax type code must be unique.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.code} - {record.name or ""}'.strip(' -')


class D406TaxCode(models.Model):
    """ANAF VAT code nomenclature — SAF-T ``TaxCode`` (6 digits).

    Source: workbook sheets ``Livrari`` and the ``Achizitii*`` family.

    ``date_start`` matters more than it looks: the 21% and 11% VAT rates are
    only valid from 2025-08-01, and a file that reports a pre-August period
    with the new codes (or vice versa) is wrong even though it is schema-valid.
    """
    _name = 'l10n.ro.d406.tax.code'
    _description = 'D406 SAF-T Tax Code (ANAF)'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    name_en = fields.Char(string='Name (EN)')
    short_code = fields.Char(
        help='ANAF short mnemonic for the code, e.g. L1 or A1_100.')
    section = fields.Char(
        index=True,
        help='Workbook sheet the code was generated from, e.g. livrari.')
    vat_rate = fields.Float(digits=(5, 2), string='VAT Rate (%)')
    date_start = fields.Date()
    date_end = fields.Date()
    is_active = fields.Boolean(
        default=True,
        help='False when ANAF marks the code as withdrawn.')
    note = fields.Char()

    _code_uniq = models.Constraint(
        'unique(code)',
        'The ANAF tax code must be unique.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.code} - {record.name or ""}'.strip(' -')

    @api.model
    def valid_on(self, date):
        """Return the codes valid on a given date."""
        return self.search([
            ('is_active', '=', True),
            '|', ('date_start', '=', False), ('date_start', '<=', date),
            '|', ('date_end', '=', False), ('date_end', '>=', date),
        ])


class D406Account(models.Model):
    """ANAF statutory chart-of-accounts nomenclature.

    Source: workbook sheet ``PlanConturiBalSocCom`` (commercial companies).
    ``chart`` exists so the other statutory charts ANAF publishes (IFRS,
    banks, insurers, NGOs) can be added later without a schema change.
    """
    _name = 'l10n.ro.d406.account'
    _description = 'D406 SAF-T Chart of Accounts (ANAF)'
    _order = 'chart, code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    name_en = fields.Char(string='Name (EN)')
    chart = fields.Char(
        required=True, default='bal_soc_com', index=True,
        help='Statutory chart this code belongs to.')

    _code_chart_uniq = models.Constraint(
        'unique(chart, code)',
        'An ANAF account code must be unique within its chart.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.code} - {record.name or ""}'.strip(' -')

    @api.model
    def code_set(self, chart='bal_soc_com'):
        """Return the chart's codes as a ``set`` for fast prefix resolution."""
        rows = self.search_read([('chart', '=', chart)], ['code'])
        return {row['code'] for row in rows}


class D406UomCode(models.Model):
    """UN/ECE unit-of-measure nomenclature — SAF-T ``UOMTableEntry``.

    Source: workbook sheet ``Unitati_masura``.

    This table exists for one reason: ``UOMTableEntry/Description`` is
    mandatory in the schema and Odoo has no source for a UN/ECE description.
    Omitting it is a confirmed rejection
    (``elementul 'Description' ar fi trebuit sa apara de minimum 1 ori``).
    """
    _name = 'l10n.ro.d406.uom.code'
    _description = 'D406 SAF-T Unit of Measure (UN/ECE)'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    name_en = fields.Char(string='Name (EN)')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The UN/ECE unit code must be unique.',
    )

    @api.model
    def description_for(self, code):
        """Return a description for a UN/ECE code, never blank.

        Falls back to the code itself so the mandatory element can always be
        emitted; the pre-flight report lists codes that had no description.
        """
        if not code:
            return ''
        record = self.search([('code', '=', code)], limit=1)
        return record.name or record.name_en or code


class D406InvoiceType(models.Model):
    """ANAF invoice type nomenclature — SAF-T ``InvoiceType``.

    Source: workbook sheet ``Nom_Tipuri_facturi`` (derived from EN 16931).
    """
    _name = 'l10n.ro.d406.invoice.type'
    _description = 'D406 SAF-T Invoice Type (ANAF)'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    name_en = fields.Char(string='Name (EN)')
    en16931_type = fields.Char(string='EN 16931 Interpretation')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The invoice type code must be unique.',
    )


class D406PaymentMethod(models.Model):
    """ANAF payment method nomenclature — SAF-T ``PaymentMethod``.

    Source: workbook sheet ``Nom_Mecanisme_plati``.
    """
    _name = 'l10n.ro.d406.payment.method'
    _description = 'D406 SAF-T Payment Method (ANAF)'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    mechanism_code = fields.Char(
        help='ANAF payment mechanism code the method is reported under.')
    name = fields.Char(required=True)
    name_en = fields.Char(string='Name (EN)')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The payment method code must be unique.',
    )

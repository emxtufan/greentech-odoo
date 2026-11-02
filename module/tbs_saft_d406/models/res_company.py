# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Company-level D406 configuration."""
from odoo import fields, models

#: ``Header/TaxAccountingBasis``. These are the ten values the XSD actually
#: accepts via ``xs:restriction``. ANAF's own documentation block inside the
#: same file lists twelve (adding ``ONGE`` and ``BNR6``), but a file using
#: those fails XSD validation today. The selection is kept here in one place
#: so it can be extended the moment ANAF fixes the schema.
TAX_ACCOUNTING_BASIS = [
    ('A', 'A - Contabilitate în partidă simplă'),
    ('I', 'I - Contabilitate în partidă dublă'),
    ('IFRS', 'IFRS - Standarde internaționale de raportare financiară'),
    ('BANK', 'BANK - Instituții de credit'),
    ('INSURANCE', 'INSURANCE - Societăți de asigurări'),
    ('NORMA39', 'NORMA39 - Norma ASF 39/2015'),
    ('IFN', 'IFN - Instituții financiare nebancare'),
    ('NORMA36', 'NORMA36 - Norma ASF 36/2015'),
    ('NORMA14', 'NORMA14 - Norma ASF 14/2015'),
    ('ONG', 'ONG - Organizații non-guvernamentale'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ro_d406_tax_accounting_basis = fields.Selection(
        selection=TAX_ACCOUNTING_BASIS,
        string='SAF-T Accounting Basis',
        default='I',
        help='Reported as <TaxAccountingBasis> in the D406 header. Most '
             'commercial companies use double-entry accounting (I).',
    )
    l10n_ro_d406_tax_entity = fields.Char(
        string='SAF-T Tax Entity',
        help='Optional <TaxEntity> value. Used by taxpayers who report '
             'separate divisions; leave empty otherwise.',
    )
    l10n_ro_d406_chart = fields.Char(
        string='SAF-T Statutory Chart',
        default='bal_soc_com',
        help='Which ANAF statutory chart of accounts this company reports '
             'against. Only the commercial-company chart is shipped today.',
    )

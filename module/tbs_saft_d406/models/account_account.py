# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Mapping of the company chart of accounts onto the ANAF nomenclature."""
from odoo import _, api, fields, models

from ..d406 import accountmap


class AccountAccount(models.Model):
    _inherit = 'account.account'

    # Not stored. In Odoo 19 ``account.account.code`` is itself a non-stored
    # computed field backed by the company-dependent ``code_store``, so a
    # stored compute keyed on it would be wrong under multi-company. The
    # export resolves every account once per run, which is cheap.
    l10n_ro_d406_account_code = fields.Char(
        string='SAF-T Account Code',
        compute='_compute_l10n_ro_d406_account_code',
        help='ANAF chart-of-accounts code this account is reported under in '
             'the D406 declaration. Resolved automatically from the account '
             'code; set a manual code below to override it.',
    )
    l10n_ro_d406_account_code_manual = fields.Char(
        string='SAF-T Account Code (manual)',
        company_dependent=True,
        help='Overrides the automatically resolved ANAF code. Use this for '
             'custom accounts that do not follow the statutory numbering.',
    )
    l10n_ro_d406_mapping_status = fields.Selection(
        selection=[
            (accountmap.Resolution.EXACT, 'Exact match'),
            (accountmap.Resolution.PREFIX, 'Matched by prefix'),
            (accountmap.Resolution.OVERRIDE, 'Manual override'),
            (accountmap.Resolution.UNRESOLVED, 'Not in ANAF chart'),
            (accountmap.Resolution.NOT_NUMERIC, 'Code is not numeric'),
        ],
        string='SAF-T Mapping',
        compute='_compute_l10n_ro_d406_account_code',
        help='How the ANAF code was resolved. Anything other than a match '
             'will be rejected by DUKIntegrator.',
    )
    l10n_ro_d406_mapping_message = fields.Char(
        string='SAF-T Mapping Note',
        compute='_compute_l10n_ro_d406_account_code',
    )
    l10n_ro_d406_account_type = fields.Selection(
        selection=[
            ('Activ', 'Activ'),
            ('Pasiv', 'Pasiv'),
            ('Bifunctional', 'Bifuncțional'),
        ],
        string='SAF-T Account Type',
        company_dependent=True,
        help='Romanian statutory account direction reported as '
             '<AccountType>. Leave empty to derive it from the Odoo account '
             'type; set it explicitly for two-way accounts such as VAT '
             'settlement or current accounts with associates.',
    )

    @api.depends('code', 'l10n_ro_d406_account_code_manual')
    def _compute_l10n_ro_d406_account_code(self):
        anaf_codes = self.env['l10n.ro.d406.account'].code_set()
        for account in self:
            resolution = accountmap.resolve(
                account.code,
                anaf_codes,
                override=account.l10n_ro_d406_account_code_manual,
            )
            account.l10n_ro_d406_account_code = resolution.anaf_code
            account.l10n_ro_d406_mapping_status = resolution.method
            account.l10n_ro_d406_mapping_message = resolution.message

    def l10n_ro_d406_saft_account_type(self):
        """Return the SAF-T ``AccountType`` for this account."""
        self.ensure_one()
        return accountmap.saft_account_type(
            self.account_type, self.l10n_ro_d406_account_type)

    @api.model
    def l10n_ro_d406_unmapped_accounts(self):
        """Accounts that would be rejected by DUKIntegrator.

        Used by the pre-flight check on the export wizard so the user fixes
        the chart before generating a file rather than after ANAF bounces it.
        """
        accounts = self.search([])
        return accounts.filtered(
            lambda a: a.l10n_ro_d406_mapping_status in (
                accountmap.Resolution.UNRESOLVED,
                accountmap.Resolution.NOT_NUMERIC,
            )
        )

    def action_l10n_ro_d406_open_unmapped(self):
        """Open the list of accounts with an unusable SAF-T mapping."""
        unmapped = self.l10n_ro_d406_unmapped_accounts()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Accounts without a valid SAF-T code'),
            'res_model': 'account.account',
            'view_mode': 'list,form',
            'domain': [('id', 'in', unmapped.ids)],
        }

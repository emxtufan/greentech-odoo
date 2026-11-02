# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Export wizard for the D406 SAF-T declaration."""
import base64
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..d406.xmlbuilder import EmptyRequiredValue
from ..models.d406_generator import DECLARATION_TYPES


class D406ExportWizard(models.TransientModel):
    _name = 'l10n.ro.d406.export.wizard'
    _description = 'Export D406 SAF-T'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)])
    declaration_type = fields.Selection(
        selection=DECLARATION_TYPES, required=True, default='L',
        string='Declaration Type',
        help='Reported as <HeaderComment>. It tells ANAF which sections the '
             'file is allowed to contain.')
    date_from = fields.Date(required=True, default=lambda self: self._default_date_from())
    date_to = fields.Date(required=True, default=lambda self: self._default_date_to())
    segment_index = fields.Integer(
        default=1,
        help='Segment number when a large period is split across files.')
    total_segments = fields.Integer(
        default=1, string='Total Segments')

    state = fields.Selection(
        selection=[('draft', 'Draft'), ('done', 'Generated')],
        default='draft')
    attachment_id = fields.Many2one('ir.attachment', readonly=True)
    xsd_valid = fields.Boolean(readonly=True, string='Schema Valid')
    validation_log = fields.Text(readonly=True)
    duk_available = fields.Boolean(compute='_compute_duk_available')

    @api.model
    def _default_date_from(self):
        previous_month = fields.Date.context_today(self) - relativedelta(months=1)
        return previous_month.replace(day=1)

    @api.model
    def _default_date_to(self):
        first_of_month = fields.Date.context_today(self).replace(day=1)
        return first_of_month - relativedelta(days=1)

    @api.depends_context('uid')
    def _compute_duk_available(self):
        available = self.env['l10n.ro.d406.validator'].is_duk_available()
        for wizard in self:
            wizard.duk_available = available

    # ------------------------------------------------------------------
    # Pre-flight
    # ------------------------------------------------------------------

    def action_check(self):
        """Report configuration problems before generating anything.

        The point is to fail on a screen the accountant can act on, rather
        than on ANAF's rejection notice two days later.
        """
        self.ensure_one()
        problems = self._collect_problems()
        self.validation_log = '\n'.join(problems) if problems else _(
            'No configuration problems found. The file can be generated.')
        return self._reopen()

    def _collect_problems(self):
        problems = []
        unmapped_accounts = self.env['account.account'].l10n_ro_d406_unmapped_accounts()
        if unmapped_accounts:
            problems.append(_(
                '%(count)s account(s) have no valid ANAF code and will be '
                'rejected: %(codes)s',
                count=len(unmapped_accounts),
                codes=', '.join(unmapped_accounts.mapped('code')[:20]),
            ))
        unmapped_taxes = self.env['account.tax'].l10n_ro_d406_unmapped_taxes()
        if unmapped_taxes:
            problems.append(_(
                '%(count)s tax(es) have no SAF-T code; their transactions '
                'will be reported as untaxed: %(names)s',
                count=len(unmapped_taxes),
                names=', '.join(unmapped_taxes.mapped('name')[:20]),
            ))
        if not self.company_id.l10n_ro_d406_tax_accounting_basis:
            problems.append(_('The company has no SAF-T accounting basis set.'))
        if not self.company_id.partner_id.city or not self.company_id.partner_id.country_id:
            problems.append(_(
                'The company address needs at least a city and a country.'))
        return problems

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def action_generate(self):
        self.ensure_one()
        xml_bytes = self._generate_xml()
        attachment = self.env['ir.attachment'].create({
            'name': self._filename(),
            'raw': xml_bytes,
            'mimetype': 'application/xml',
            'res_model': self._name,
            'res_id': self.id,
        })
        valid, messages = self.env['l10n.ro.d406.validator'].validate_xsd(xml_bytes)
        self.write({
            'attachment_id': attachment.id,
            'state': 'done',
            'xsd_valid': valid,
            'validation_log': self._format_log(valid, messages),
        })
        return self._reopen()

    def _generate_xml(self):
        # The ledger aggregation runs as raw SQL, which record rules do not
        # reach. The company boundary therefore has to be asserted here,
        # explicitly, rather than left to an ir.rule that never sees the
        # query.
        if self.company_id not in self.env.companies:
            raise AccessError(_(
                'You do not have access to company %s.',
                self.company_id.display_name))
        options = {
            'company': self.company_id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'declaration_type': self.declaration_type,
            'segment_index': self.segment_index or 1,
            'total_segments': self.total_segments or 1,
            'creation_date': fields.Date.context_today(self),
            'fiscal_year_start': self._fiscal_year_start(),
            'software_version': self._software_version(),
        }
        try:
            return self.env['l10n.ro.d406.generator'].generate(options)
        except EmptyRequiredValue as error:
            raise UserError(_(
                'The declaration could not be generated because a mandatory '
                'value is missing:\n\n%(error)s',
                error=error,
            )) from error

    def _fiscal_year_start(self):
        """First day of the fiscal year containing ``date_from``.

        Profit-and-loss opening balances restart here; balance-sheet accounts
        ignore it.
        """
        dates = self.company_id.compute_fiscalyear_dates(self.date_from)
        return dates['date_from']

    def _software_version(self):
        module = self.env['ir.module.module'].sudo().search(
            [('name', '=', 'tbs_saft_d406')], limit=1)
        return module.latest_version or module.installed_version or '19.0.1.0.0'

    def _filename(self):
        return (
            f'D406_{self.company_id.vat or self.company_id.id}_'
            f'{self.declaration_type}_'
            f'{self.date_from:%Y%m}_{self.date_to:%Y%m}.xml'
        )

    def _format_log(self, valid, messages):
        if valid:
            header = _('Schema validation passed against the official ANAF XSD.')
            footer = _(
                'Note: the schema does not encode ANAF business rules. Run '
                'DUKIntegrator before submitting.')
            return f'{header}\n\n{footer}'
        body = '\n'.join(messages[:100])
        more = ''
        if len(messages) > 100:
            more = _('\n... and %(count)s more.', count=len(messages) - 100)
        return _('Schema validation FAILED:\n\n%(body)s%(more)s',
                 body=body, more=more)

    # ------------------------------------------------------------------
    # DUK
    # ------------------------------------------------------------------

    def action_validate_duk(self):
        """Run the generated file through DUKIntegrator, when available."""
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_('Generate the file first.'))
        valid, messages = self.env['l10n.ro.d406.validator'].validate_duk(
            self.attachment_id.raw,
            year=self.date_to.year,
            month=self.date_to.month,
        )
        status = _('DUKIntegrator: VALID') if valid else _('DUKIntegrator: REJECTED')
        self.validation_log = status + '\n\n' + '\n'.join(messages[:200])
        return self._reopen()

    def action_download(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_('Generate the file first.'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.attachment_id.id}?download=true',
            'target': 'self',
        }

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

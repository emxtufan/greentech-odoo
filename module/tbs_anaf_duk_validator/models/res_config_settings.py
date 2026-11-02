# -*- coding: utf-8 -*-

from odoo import fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    tbs_anaf_duk_path = fields.Char(
        string='DUKIntegrator Path',
        config_parameter='tbs_anaf_duk_validator.duk_path',
        help=(
            'Server folder holding the DUKIntegrator .jar files (ANAF\'s '
            'official validator). Default: /var/odoo/dukintegrator. Leave '
            'empty to use the default.'
        ),
    )

    def action_tbs_anaf_duk_check_installation(self):
        """Check DUKIntegrator is installed at the configured path and
        surface the result as a notification, so a client can self-verify
        their setup without server/log access."""
        result = self.env['anaf.duk.validator'].check_installation()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('DUKIntegrator instalat') if result['installed']
                else _('DUKIntegrator negăsit'),
                'message': result['message'],
                'type': 'success' if result['installed'] else 'warning',
                'sticky': not result['installed'],
            },
        }

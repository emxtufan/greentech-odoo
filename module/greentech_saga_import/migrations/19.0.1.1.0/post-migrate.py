from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for batch in env['saga.import.batch'].search([('state', '=', 'done')]):
        batch._prepare_operations()
        batch._set(report=batch._report_html(batch.result_json, done=True))
    for batch in env['saga.import.batch'].search([('state', '=', 'blocked')]):
        if batch.result_json:
            batch._set(report=batch._report_html(batch.result_json))

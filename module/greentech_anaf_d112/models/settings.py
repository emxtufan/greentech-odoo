from odoo import fields, models
from odoo.exceptions import AccessError
from ..services import duk


class Settings(models.TransientModel):
    _inherit = "res.config.settings"

    gt_anaf_java_path = fields.Char("Executabil Java", config_parameter="gt_anaf.java_path")
    gt_anaf_duk_dir = fields.Char("Director DUKIntegrator", config_parameter="gt_anaf.duk_dir")

    def action_check_anaf_runtime(self):
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise AccessError("Configurarea validatorului este rezervată administratorului.")
        duk_dir = duk.resolve_duk_dir(self.env, "gt_anaf.duk_dir", "duk")
        java = duk.resolve_java(self.env)
        _, issues = duk.readiness(duk_dir, java)
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": "Validator ANAF", "message": "\n".join(issues) if issues else
            "Fișierele sunt disponibile. Următorul pas: validarea unei declarații.",
            "type": "warning" if issues else "success", "sticky": True,
        }}

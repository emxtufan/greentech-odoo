"""Executed inside Odoo shell; all temporary ORM changes are rolled back."""
import json
from pathlib import Path

ROOT = Path.cwd()
WORK = ROOT / "logs/oca-ro-install-20261020"
selected = set(json.loads((WORK / "selection.json").read_text())["modules"])
result = {"views": [], "reports": [], "registry_missing_check": None}
try:
    # Compile every supplied form/list/search view in the user context. This
    # catches inherited XPath, unknown field and access metadata regressions.
    admin = env.ref("base.user_admin")
    data = env["ir.model.data"].search([
        ("module", "in", sorted(selected)), ("model", "=", "ir.ui.view")
    ])
    views = env["ir.ui.view"].browse(data.mapped("res_id")).exists().filtered(
        lambda v: v.active and v.type in ("form", "list", "search", "kanban")
    )
    for view in views:
        env[view.model].with_user(admin).with_context(lang="ro_RO").get_view(
            view_id=view.id, view_type=view.type
        )
        result["views"].append({"id": view.id, "model": view.model, "type": view.type})
    invoice = env["account.move"].search([
        ("move_type", "=", "out_invoice"), ("state", "=", "posted")
    ], limit=1)
    if invoice:
        rendered, _ = env["ir.actions.report"].with_context(lang="ro_RO")._render_qweb_html(
            "account.account_invoices", docids=invoice.ids
        )
        assert b"<html" in rendered or b"article" in rendered
        result["reports"].append({"name": "invoice", "bytes": len(rendered)})
    # No file means no false verification date, even when editing a real RO CIF.
    import odoo.tools
    if not (Path(odoo.tools.config["data_dir"]) / "istoric.txt").exists():
        # Transient record: synthetic identifier is never saved or sent to ANAF.
        for vat in ("RO123456", "123456"):
            partner = env["res.partner"].new({
                "name": "ANAF parser smoke check", "country_id": env.ref("base.ro").id,
                "vat": vat, "l10n_ro_vat_on_payment": True,
            })
            before = (partner.l10n_ro_vat_on_payment, partner.l10n_ro_vat_payment_check_date)
            assert partner.check_vat_on_payment() is False
            assert before == (partner.l10n_ro_vat_on_payment, partner.l10n_ro_vat_payment_check_date)
        result["registry_missing_check"] = "unchanged and unverified"
    result["database"] = env.cr.dbname
    result["status"] = "passed"
    (WORK / "smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("OCA_SMOKE_OK", len(result["views"]), "views", len(result["reports"]), "reports")
finally:
    env.cr.rollback()

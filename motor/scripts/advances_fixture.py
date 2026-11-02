"""Browser fixtures on the disposable clone only; no writes to the live company."""
import json
from pathlib import Path
from odoo import Command

root = Path.cwd()
work = root / "logs/advances-20261020"
assert env.cr.dbname == json.loads((work / "state.json").read_text())["database"]
company = env["res.company"].browse(1)
assert company.name == "GreenTech Financiar DEMO - date fictive"
local = env(context=dict(env.context, allowed_company_ids=[1], tracking_disable=True,
                         no_insert=True, no_vat_validation=True))
assert not (work / "fixture.json").exists(), "Fixtures already prepared"
partner = local["res.partner"].create({"name": "DEMO AVANSURI - test izolat", "company_id": 1})
result = {"partner": partner.id, "company": 1, "cases": {}}
for kind in ("sale", "purchase"):
    tax = local["account.tax"].search([
        ("company_id", "=", 1), ("type_tax_use", "=", kind), ("amount", "=", 21),
        ("amount_type", "=", "percent"), ("tax_exigibility", "=", "on_invoice")], limit=1)
    advance_account = local["account.account"].search([
        ("company_ids", "in", [1]), ("code", "=", "419000" if kind == "sale" else "409200")], limit=1)
    ordinary_account = local["account.account"].search([
        ("company_ids", "in", [1]), ("code", "=", "704000" if kind == "sale" else "628000")], limit=1)
    assert tax and advance_account and ordinary_account
    create = local["gt.advance.create"].create({
        "company_id": 1, "kind": kind, "partner_id": partner.id, "date": "2026-09-10",
        "ref": "DEMO-AVANS-" + kind.upper(),
        "line_ids": [Command.create({"name": "Avans servicii demonstrative", "account_id": advance_account.id,
                                    "amount": 1000, "tax_ids": [Command.set(tax.ids)]})]})
    final = local["account.move"].create({
        "company_id": 1, "partner_id": partner.id,
        "move_type": "out_invoice" if kind == "sale" else "in_invoice",
        "date": "2026-09-20", "invoice_date": "2026-09-20", "ref": "DEMO-FINAL-" + kind.upper(),
        "invoice_line_ids": [Command.create({
            "name": "Servicii demonstrative", "account_id": ordinary_account.id, "price_unit": 2500,
            "quantity": 1, "tax_ids": [Command.set(tax.ids)]})]})
    report = local["gt.advance.report"].create({
        "company_id": 1, "kind": kind, "partner_id": partner.id,
        "date_from": "2026-09-01", "date_to": "2026-09-30"})
    result["cases"][kind] = {"create": create.id, "final": final.id, "report": report.id}
env.cr.commit()
(work / "fixture.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("ADVANCES_BROWSER_FIXTURES_READY")

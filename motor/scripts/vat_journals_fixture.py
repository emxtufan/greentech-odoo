"""Executed through Odoo shell ONLY in the isolated test clone."""
import json
from pathlib import Path
from odoo import Command

assert env.cr.dbname.startswith("gt_d112_")
root = Path.cwd()
company = env["res.company"].search([("name", "=", "GreenTech Financiar DEMO - date fictive")])
assert len(company) == 1
local = env(context=dict(env.context, allowed_company_ids=company.ids,
                        tracking_disable=True, no_insert=True, no_vat_validation=True))
company.tax_exigibility = True
partner = local["res.partner"].search([("name", "=", "TEST UI JURNALE TVA")], limit=1)
assert not partner, "Fixture already exists"
partner = local["res.partner"].create({"name": "TEST UI JURNALE TVA"})
bank = local["account.journal"].search([("company_id", "=", company.id), ("type", "=", "bank")], limit=1)
invoices = []
for kind in ("purchase", "sale"):
    for cash in (False, True):
        tax = local["account.tax"].search([
            ("company_id", "=", company.id), ("type_tax_use", "=", kind), ("amount", "=", 21),
            ("amount_type", "=", "percent"),
            ("tax_exigibility", "=", "on_payment" if cash else "on_invoice")], order="id", limit=1)
        account = local["account.account"].search([
            ("company_ids", "in", company.ids),
            ("account_type", "=", "expense" if kind == "purchase" else "income")], limit=1)
        inv = local["account.move"].create({
            "company_id": company.id, "partner_id": partner.id,
            "move_type": "in_invoice" if kind == "purchase" else "out_invoice",
            "date": "2026-08-10" if cash else "2026-09-10",
            "invoice_date": "2026-08-10" if cash else "2026-09-10",
            "ref": f"TEST-{kind}-{'TVA-PLATA' if cash else 'NORMAL'}",
            "invoice_line_ids": [Command.create({
                "name": "Test software jurnal", "account_id": account.id, "quantity": 1,
                "price_unit": 2000 if cash else 1000, "tax_ids": [Command.set(tax.ids)]})],
        })
        inv.action_post()
        invoices.append(inv.id)
        if cash:
            term = inv.line_ids.filtered(lambda l: l.account_id.account_type in ("liability_payable", "asset_receivable"))[:1]
            sign = -1 if term.balance > 0 else 1
            payment = local["account.move"].create({
                "company_id": company.id, "journal_id": bank.id, "date": "2026-09-15",
                "ref": "TEST plata partiala",
                "line_ids": [Command.create({
                    "account_id": term.account_id.id, "partner_id": partner.id,
                    "debit": max(sign * 1210, 0), "credit": max(-sign * 1210, 0)}),
                    Command.create({"account_id": bank.default_account_id.id,
                                    "debit": max(-sign * 1210, 0), "credit": max(sign * 1210, 0)})]})
            payment.action_post()
            (term | payment.line_ids.filtered(lambda l: l.account_id == term.account_id)).reconcile()
result = {"company_id": company.id, "partner_id": partner.id, "invoices": invoices, "reports": {}}
for kind in ("purchase", "sale"):
    report = local["gt.ro.vat.journal"].create({
        "company_id": company.id, "kind": kind, "partner_id": partner.id,
        "date_from": "2026-09-01", "date_to": "2026-09-30"})
    report.action_refresh()
    totals = report.data["totals"]
    assert (totals["base"], totals["vat"], totals["eligible"], totals["pending_vat"]) == (3000, 630, 420, 210), totals
    result["reports"][kind] = report.id
env.cr.commit()
(root / "logs/vat-journals-20261020/fixture.json").write_text(json.dumps(result, indent=2))
print("VAT_JOURNAL_FIXTURE_READY", result)

"""Create synthetic D406 evidence only in the isolated test database."""
import subprocess
import d112_deploy as base

base.WORK = base.ROOT / "logs/tbs-modules-20261020"
code = r'''
import json
from pathlib import Path
from odoo import Command
assert env.cr.dbname == json.loads(Path("logs/tbs-modules-20261020/state.json").read_text())["database"]
name = "DEMO SAF-T - teste izolate"
company = env["res.company"].search([("name", "=", name)], limit=1)
if not company:
    company = env["res.company"].create({
        "name": name, "country_id": env.ref("base.ro").id, "vat": "RO12345674",
        "street": "Strada Demonstratiei 1", "city": "Sibiu", "zip": "550001",
        "phone": "0269000000", "email": "demo@example.test",
    })
    env["account.chart.template"].try_loading("ro", company=company, install_demo=False)
    env.user.company_ids |= company
    env["res.partner.bank"].create({
        "partner_id": company.partner_id.id, "company_id": company.id,
        "acc_number": "RO49AAAA1B31007593840000",
    })
scope = env(context=dict(env.context, allowed_company_ids=[company.id]))
company.company_registry = "DEMO-SAFT-ISOLATED"
company.partner_id.company_id = company
login = json.loads(Path("config/acces-financiar-test.json").read_text())["login"]
env["res.users"].search([("login", "=", login)], limit=1).company_ids |= company
taxes = {}
for kind, code in (("sale", "310344"), ("purchase", "301104")):
    tax = scope["account.tax"].search([
        ("company_id", "=", company.id), ("type_tax_use", "=", kind),
        ("amount_type", "=", "percent"), ("amount", "=", 21)], limit=1)
    assert tax
    tax.write({
        "l10n_ro_d406_tax_type_id": scope["l10n.ro.d406.tax.type"].search([("code", "=", "301")]).id,
        "l10n_ro_d406_tax_code_id": scope["l10n.ro.d406.tax.code"].search([("code", "=", code)]).id,
    })
    taxes[kind] = tax
partner = scope["res.partner"].search([("name", "=", "Partener DEMO SAF-T")], limit=1)
if not partner:
    partner = scope["res.partner"].create({
        "name": "Partener DEMO SAF-T", "is_company": True, "vat": "RO99999992",
        "country_id": env.ref("base.ro").id, "city": "Cluj-Napoca", "zip": "400001",
        "street": "Strada Exemplu 1",
    })
product = scope["product.product"].search([("default_code", "=", "GT-SAFT-TEST")], limit=1)
partner.company_registry = "DEMO-SAFT-PARTNER"
partner.company_id = company
if not product:
    product = scope["product.product"].create({"name": "Servicii DEMO SAF-T", "type": "service", "default_code": "GT-SAFT-TEST"})
invoices = scope["account.move"].search([("company_id", "=", company.id), ("state", "=", "posted")])
if not invoices:
    for kind, amount, move_type in (("sale", 1000, "out_invoice"), ("purchase", 250, "in_invoice")):
        move = scope["account.move"].create({
            "company_id": company.id, "move_type": move_type, "partner_id": partner.id,
            "invoice_date": "2026-09-15", "date": "2026-09-15",
            "invoice_line_ids": [Command.create({
                "product_id": product.id, "name": "Servicii demonstrative", "quantity": 1, "price_unit": amount,
                "tax_ids": [Command.set(taxes[kind].ids)],
            })],
        })
        move.action_post()
        journal = scope["account.journal"].search([("company_id", "=", company.id), ("type", "=", "bank")], limit=1)
        counterpart = move.line_ids.filtered(lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")).account_id
        signed = amount * 1.21 * (1 if kind == "sale" else -1)
        payment = scope["account.move"].create({
            "company_id": company.id, "journal_id": journal.id, "date": "2026-09-20", "ref": "Plata demonstrativa",
            "line_ids": [Command.create({"account_id": journal.default_account_id.id, "debit": max(signed, 0), "credit": max(-signed, 0)}),
                         Command.create({"account_id": counterpart.id, "partner_id": partner.id, "debit": max(-signed, 0), "credit": max(signed, 0)})],
        })
        payment.action_post()
wizard = scope["l10n.ro.d406.export.wizard"].create({
    "company_id": company.id, "date_from": "2026-09-01", "date_to": "2026-09-30",
    "gt_contact_first": "Ana", "gt_contact_last": "Demonstratie",
})
wizard.action_generate()
assert wizard.xsd_valid, wizard.validation_log
wizard.action_validate_duk()
bad = scope["anaf.duk.validator"].validate(
    wizard.attachment_id.raw.replace(b"12345674", b"12345670"),
    "D406", year=2026, month=9)
assert not bad["success"], "Official validator accepted invalid CUI"
Path("logs/tbs-modules-20261020/negative-validation.txt").write_text(bad.get("errors", ""), encoding="utf-8")
if wizard.gt_duk_valid:
    wizard.action_generate_pdf()
work = Path("logs/tbs-modules-20261020")
(work / "fixture.xml").write_bytes(wizard.attachment_id.raw)
if wizard.gt_pdf_id:
    Path("output/pdf/D406_DEMO_2026_09.pdf").write_bytes(wizard.gt_pdf_id.raw)
    Path("output/pdf/D406_DEMO_2026_09.xml").write_bytes(wizard.attachment_id.raw)
(work / "fixture-validation.txt").write_text(wizard.validation_log, encoding="utf-8")
data = {"company": company.id, "wizard": wizard.id, "xsd_valid": wizard.xsd_valid, "duk_valid": wizard.gt_duk_valid,
        "pdf": bool(wizard.gt_pdf_id)}
(work / "fixture.json").write_text(json.dumps(data, indent=2))
env.cr.commit()
print("D406_FIXTURE", json.dumps(data))
'''
result = subprocess.run(
    [str(base.PYTHON), str(base.ODOO), "shell", "-c", str(base.WORK / "test.conf"), "--no-http"],
    input=code, text=True, encoding="utf-8", cwd=base.ROOT, env=base.ENV,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(base.WORK / "fixture.log").write_text(result.stdout, encoding="utf-8")
print(result.stdout[-2200:])
assert result.returncode == 0

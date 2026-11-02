"""Executed inside an Odoo shell transaction by d112_demo_setup.py."""
import base64
import json
from pathlib import Path

from odoo.addons.greentech_anaf_d112.services import document

assert (TARGET == "live" and env.cr.dbname == "greentech_financiar_test") or (
    TARGET == "test" and env.cr.dbname.startswith("gt_d112_"))
COMPANY_NAME = "GreenTech Financiar DEMO - date fictive"
company = env["res.company"].search([("name", "=", COMPANY_NAME)])
assert len(company) == 1
local = env(context=dict(env.context, allowed_company_ids=company.ids, tracking_disable=True,
                         mail_create_nosubscribe=True, mail_notify_force_send=False))
work = Path.cwd() / "logs/d112-demo-20261020"

# Ensure the real imported firm's HR records are byte-for-byte unchanged.
def other_hr_snapshot():
    env.flush_all()
    data = {}
    for table in ("hr_employee", "hr_version"):
        env.cr.execute(f"SELECT id, to_jsonb(t)::text FROM {table} t WHERE company_id <> %s ORDER BY id", (company.id,))
        data[table] = env.cr.fetchall()
    return data

before_hr = other_hr_snapshot()
people = local["hr.employee"].search([("company_id", "=", company.id), ("gt_payroll_demo", "=", True)])
expected = {"Ion Popescu [DEMO]", "Mara Ionescu [DEMO]", "Radu Dumitrescu [DEMO]"}
assert set(people.mapped("name")) == expected, "Unexpected demo employee set; do not alter unknown records."
admin = local["hr.employee"].search([("company_id", "=", company.id), ("name", "=", "Administrator")])
assert len(admin) == 1 and not admin.version_id.contract_date_start and admin.version_id.wage == 0
admin.write({"ro_d112_non_payroll": True,
             "ro_d112_exclusion_reason": "Fișă tehnică a utilizatorului Administrator; fără contract individual de muncă și fără salariu."})

def cnp(prefix):
    check = sum(int(a) * int(b) for a, b in zip(prefix, "279146358279")) % 11
    return prefix + str(1 if check == 10 else check)

body = "9000100"
check = sum(int(a) * int(b) for a, b in zip(body.zfill(9), "753217532")) * 10 % 11
fictional_cui = body + str(0 if check == 10 else check)
assert not company.vat or company.vat == fictional_cui, "Existing company VAT differs; stop before replacing it."
company.with_context(no_vat_validation=True).write({"vat": fictional_cui, "l10n_ro_caen_code": "4321"})
specs = {
    "Ion Popescu [DEMO]": ("POPESCU", "ION DEMO", "190010140901", "1990-01-01", 0),
    "Mara Ionescu [DEMO]": ("IONESCU", "MARA DEMO", "292020240902", "1992-02-02", 1),
    "Radu Dumitrescu [DEMO]": ("DUMITRESCU", "RADU DEMO", "188030340903", "1988-03-03", 0),
}
for employee in people:
    last, first, prefix, birth, children = specs[employee.name]
    assert employee.version_id.contract_date_start and employee.version_id.wage > 0
    employee.write({
        "identification_id": cnp(prefix), "birthday": birth, "ro_d112_last_name": last,
        "ro_d112_first_name": first, "ro_d112_house": "_B", "ro_d112_profile": "normal",
        "ro_d112_role": "primary", "ro_d112_dependents": children, "ro_d112_children": children,
        "ro_d112_minimum": "eligible",
    })

period = local["gt.ro.payroll.period"].search([("company_id", "=", company.id), ("year", "=", 2026), ("month", "=", "9")])
if period:
    assert env["ir.config_parameter"].sudo().get_param("gt_anaf.demo_seed_period") == str(period.id), "A user-owned period already exists."
    if period.state != "draft":
        period.action_reset()
else:
    period = local["gt.ro.payroll.period"].create({
        "company_id": company.id, "year": 2026, "month": "9", "caen": "4321", "house": "_B",
        "signer_last": "DEMO", "signer_first": "ADMINISTRATOR",
        "signer_position": "Administrator DEMO", "scope_confirmed": True,
    })
period.action_load_employees()
assert set(period.line_ids.employee_id.ids) == set(people.ids)
period.line_ids.write({"worked_days": 22, "bonus": 0, "confirmed": True})
period.action_compute()
assert period.state == "calculated", period.calculation_log
assert (period.gross, period.cas, period.cass, period.tax, period.net, period.cam) == (33000, 8250, 3300, 2135, 19315, 743)
declaration = local["gt.anaf.d112"].browse(period.action_generate_d112()["res_id"])
declaration.write({"filing_note": "DATE FICTIVE, EXCLUSIV TEST SOFTWARE. NU SE SEMNEAZĂ ȘI NU SE DEPUNE LA ANAF. Pontajul și identificatorii sunt sintetici."})
declaration.action_validate_anaf()
assert not declaration.filing_index and not declaration.receipt
assert declaration.insured_count == 3
assert before_hr == other_hr_snapshot(), "Unexpected change to another company's HR records."
env["ir.config_parameter"].sudo().set_param("gt_anaf.demo_seed_period", str(period.id))
raw = document.to_xml(declaration.payload)
report = {
    "company": company.name, "company_id": company.id, "year": 2026, "month": 9,
    "period_id": period.id, "declaration_id": declaration.id, "employees": len(people),
    "gross": period.gross, "cas": period.cas, "cass": period.cass, "tax": period.tax,
    "net": period.net, "cam": period.cam, "due": period.due,
    "declaration_state": declaration.state, "validator_log": declaration.duk_log,
    "other_company_hr_unchanged": True, "fictitious_only": True, "submitted": False,
}
env.cr.commit()
(work / (TARGET + "-demo.xml")).write_bytes(raw)
(work / (TARGET + "-demo.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("D112_DEMO_SEEDED_OK", json.dumps(report, ensure_ascii=True))

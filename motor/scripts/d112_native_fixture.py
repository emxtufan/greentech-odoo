"""Create browser fixtures ONLY in the recorded isolated test database."""
import json
import subprocess
import d112_native_deploy as deploy

base = deploy.base
state = json.loads((base.WORK / "state.json").read_text())
assert state["database"].startswith("gt_d112_")
code = """
from odoo import Command
from odoo.addons.greentech_ro_payroll.tests.test_native import test_cnp
assert env.cr.dbname.startswith('gt_d112_')
company = env['res.company'].with_context(no_vat_validation=True).create({
 'name': 'TEST INTERFATA SALARII NATIVE', 'vat': '90000006',
 'company_registry': 'TEST-BROWSER-NATIVE',
 'currency_id': env.ref('base.RON').id, 'country_id': env.ref('base.ro').id,
 'street': 'STRADA TEST', 'city': 'TEST',
})
local = env(context=dict(env.context, allowed_company_ids=company.ids))
cal = env.ref('resource.resource_calendar_std').copy({'name':'TEST 40h', 'company_id':company.id})
employee = local['hr.employee'].create({
 'name':'TEST INTERFATA ANGAJAT', 'company_id':company.id, 'resource_calendar_id':cal.id,
 'identification_id':test_cnp(), 'birthday':'1990-01-01', 'ro_d112_last_name':'TEST',
 'ro_d112_first_name':'INTERFATA', 'ro_d112_house':'_B', 'ro_d112_profile':'normal',
 'ro_d112_role':'primary', 'ro_d112_minimum':'eligible',
})
employee.version_id.write({'date_version':'2026-07-01','contract_date_start':'2026-07-01','wage':8000,'resource_calendar_id':cal.id})
env.ref('base.user_admin').write({'company_ids':[Command.link(company.id)], 'company_id':company.id})
env.cr.commit()
print('NATIVE_FIXTURE_READY')
"""
result = subprocess.run([str(base.PYTHON), str(base.ODOO), "shell", "-c", state["config"], "--no-http"],
                        input=code, text=True, encoding="utf-8", env=base.ENV, cwd=base.ROOT,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(base.WORK / "fixture.log").write_text(result.stdout, encoding="utf-8")
assert result.returncode == 0 and "NATIVE_FIXTURE_READY" in result.stdout
print("NATIVE_BROWSER_FIXTURE_READY")

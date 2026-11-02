"""Disambiguate the persisted synthetic UI fixture from rollback-only unit fixtures."""
import subprocess
import d112_native_deploy as deploy
b = deploy.base
code = """
assert env.cr.dbname.startswith('gt_d112_')
company = env['res.company'].search([('name','=','TEST INTERFATA SALARII NATIVE')])
assert len(company)==1
company.with_context(no_vat_validation=True).write({'vat':'90000006','company_registry':'TEST-BROWSER-NATIVE'})
env.cr.commit()
print('FIXTURE_UNIQUE_OK')
"""
r = subprocess.run([str(b.PYTHON), str(b.ODOO), "shell", "-c", str(b.WORK / "test.conf"), "--no-http"],
                   input=code, text=True, encoding="utf-8", env=b.ENV, cwd=b.ROOT,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(b.WORK / "fixture-fix.log").write_text(r.stdout, encoding="utf-8")
assert r.returncode == 0 and "FIXTURE_UNIQUE_OK" in r.stdout
print("FIXTURE_UNIQUE_OK")

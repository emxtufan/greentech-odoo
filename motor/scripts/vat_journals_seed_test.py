import subprocess
from vat_journals_deploy import base

code = (base.ROOT / "scripts/vat_journals_fixture.py").read_text(encoding="utf-8")
r = subprocess.run([str(base.PYTHON), str(base.ODOO), "shell", "-c", str(base.WORK / "test.conf"), "--no-http"],
    input=code, text=True, encoding="utf-8", cwd=base.ROOT, env=base.ENV,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(base.WORK / "fixture.log").write_text(r.stdout, encoding="utf-8")
assert r.returncode == 0 and "VAT_JOURNAL_FIXTURE_READY" in r.stdout, "Inspect fixture.log"
print("VAT_JOURNAL_FIXTURE_READY")

import subprocess
import advances_deploy as deploy
b = deploy.base
r = subprocess.run([str(b.PYTHON), str(b.ODOO), "shell", "-c", str(b.WORK / "test.conf"), "--no-http"],
    input=(b.ROOT / "scripts/advances_fixture.py").read_text(encoding="utf-8"),
    text=True, encoding="utf-8", cwd=b.ROOT, env=b.ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(b.WORK / "fixture.log").write_text(r.stdout, encoding="utf-8")
assert r.returncode == 0 and "ADVANCES_BROWSER_FIXTURES_READY" in r.stdout
print("ADVANCES_BROWSER_FIXTURES_READY")

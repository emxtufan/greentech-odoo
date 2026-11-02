"""Upgrade native payroll only after tests on a fresh backed-up clone."""
import argparse
import json
import subprocess
import d112_deploy as base

base.WORK = base.ROOT / "logs/d112-native-20261020"


def install(target):
    work = base.WORK
    config = base.LIVE if target == "live" else work / "test.conf"
    if target == "live":
        assert json.loads((work / "browser-test.json").read_text())["status"] == "passed"
        assert (work / "test-verified.json").exists()
        base.stop_finance()
        assert base.snapshot(base.read_config()["options"]) == json.loads((work / "before.json").read_text())
    else:
        base.stop_test()
    opts = base.read_config(config)["options"]
    with base.connection(opts) as con, con.cursor() as cur:
        cur.execute("SELECT state FROM ir_module_module WHERE name='greentech_ro_payroll'")
        row = cur.fetchone()
    command = [str(base.PYTHON), str(base.ODOO), "-c", str(config), "--no-http", "--stop-after-init",
               "--without-demo", "-u", "greentech_anaf_d112", "--logfile", str(work / (target + "-install.log"))]
    if row and row[0] == "installed":
        command[command.index("greentech_anaf_d112")] = "greentech_anaf_d112,greentech_ro_payroll"
    else:
        command += ["-i", "greentech_ro_payroll"]
    if target == "test":
        command += ["--test-enable", "--test-tags", "/greentech_anaf_d112,/greentech_ro_payroll"]
    result = subprocess.run(command, cwd=base.ROOT, env=base.ENV, capture_output=True)
    (work / (target + "-console.log")).write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("Install/tests failed; inspect install.log")
    if target == "test":
        assert "0 failed, 0 error(s)" in (work / "test-install.log").read_text(encoding="utf-8")
    base.configure(config)
    code = """
from odoo import Command
env.ref('base.user_admin').write({'group_ids': [Command.link(env.ref('greentech_ro_payroll.group_payroll').id)]})
env.cr.commit()
print('NATIVE_PAYROLL_ACCESS_CONFIGURED')
"""
    r = subprocess.run([str(base.PYTHON), str(base.ODOO), "shell", "-c", str(config), "--no-http"],
                       input=code, text=True, encoding="utf-8", env=base.ENV, cwd=base.ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (work / (target + "-payroll-config.log")).write_text(r.stdout, encoding="utf-8")
    assert r.returncode == 0 and "NATIVE_PAYROLL_ACCESS_CONFIGURED" in r.stdout
    base.check(target)
    assert "greentech_ro_payroll" in base.snapshot(opts)["installed"]
    if target == "test":
        base.start_test()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "test", "live", "stop-test", "check-live"])
    action = parser.parse_args().action
    if action == "prepare":
        base.prepare()
    elif action == "stop-test":
        base.stop_test()
    elif action == "check-live":
        base.check("live")
    else:
        install(action)

import argparse
import json
import subprocess
import d112_deploy as base

base.WORK = base.ROOT / "logs/vat-journals-20261020"
MODULE = "greentech_ro_vat_journals"

def install(target):
    config = base.LIVE if target == "live" else base.WORK / "test.conf"
    if target == "live":
        assert json.loads((base.WORK / "browser-test.json").read_text())["status"] == "passed"
        assert (base.WORK / "test-verified.json").exists()
        base.stop_finance()
        current = base.snapshot(base.read_config()["options"])
        assert current == json.loads((base.WORK / "before.json").read_text()), "Live changed: fresh backup required"
    else:
        base.stop_test()
    log = base.WORK / f"{target}-install.log"
    opts = base.read_config(config)["options"]
    test_before = base.snapshot(opts) if target == "test" else None
    with base.connection(opts) as con, con.cursor() as cur:
        cur.execute("SELECT state FROM ir_module_module WHERE name=%s", (MODULE,))
        installed = cur.fetchone()
    command = [str(base.PYTHON), str(base.ODOO), "-c", str(config), "--no-http", "--stop-after-init",
               "--without-demo", "-u" if installed and installed[0] == "installed" else "-i", MODULE,
               "--logfile", str(log)]
    if target == "test":
        command += ["--test-enable", "--test-tags", "/" + MODULE]
    r = subprocess.run(command, cwd=base.ROOT, env=base.ENV, capture_output=True)
    (base.WORK / f"{target}-console.log").write_bytes(r.stdout + r.stderr)
    assert r.returncode == 0, "Inspect install.log"
    if target == "test":
        assert "0 failed, 0 error(s)" in log.read_text(encoding="utf-8")
    if target == "test":
        current = base.snapshot(opts)
        for key in ("moves", "lines", "payments", "unbalanced_posted", "active_cron"):
            assert current[key] == test_before[key], "Test modified accounting: " + key
        base.save_json(base.WORK / "test-verified.json", current)
    else:
        base.check(target)
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

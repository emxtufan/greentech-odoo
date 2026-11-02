"""Back up the finance database, test on a clone and install without financial changes."""
import argparse
import json
import subprocess
import d112_deploy as base

base.WORK = base.ROOT / "logs/advances-20261020"
MODULE = "greentech_ro_advances"


def install(target):
    config = base.LIVE if target == "live" else base.WORK / "test.conf"
    if target == "live":
        assert json.loads((base.WORK / "browser-test.json").read_text())["status"] == "passed"
        assert (base.WORK / "test-verified.json").exists()
        base.stop_finance()
        assert base.snapshot(base.read_config()["options"]) == json.loads((base.WORK / "before.json").read_text())
    else:
        base.stop_test()
    opts = base.read_config(config)["options"]
    before = base.snapshot(opts)
    with base.connection(opts) as con, con.cursor() as cur:
        cur.execute("SELECT state FROM ir_module_module WHERE name=%s", (MODULE,))
        installed = cur.fetchone()
    log = base.WORK / f"{target}-install.log"
    if log.exists():
        log.rename(base.WORK / f"{target}-install-{len(list(base.WORK.glob('*install*.log')))}.log")
    cmd = [str(base.PYTHON), str(base.ODOO), "-c", str(config), "--no-http", "--stop-after-init",
           "--without-demo", "-u" if installed and installed[0] == "installed" else "-i",
           MODULE + (",greentech_anaf_d300,greentech_ro_vat_journals" if target == "test" else ""),
           "--logfile", str(log)]
    if target == "test":
        cmd += ["--test-enable", "--test-tags", "/" + MODULE + ",/greentech_anaf_d300,/greentech_ro_vat_journals"]
    result = subprocess.run(cmd, cwd=base.ROOT, env=base.ENV, capture_output=True)
    (base.WORK / f"{target}-console.log").write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, "Inspect install log"
    if target == "test":
        assert "0 failed, 0 error(s)" in log.read_text(encoding="utf-8"), "Tests failed"
    current = base.snapshot(opts)
    for key in ("moves", "lines", "payments", "unbalanced_posted", "active_cron"):
        assert current[key] == before[key], "Accounting changed: " + key
    assert MODULE in current["installed"]
    base.save_json(base.WORK / f"{target}-verified.json", current)
    print("ADVANCES_INSTALLED_ACCOUNTING_UNCHANGED", target)
    if target == "test":
        base.start_test()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "test", "live", "stop-test"])
    action = parser.parse_args().action
    if action == "prepare":
        base.prepare()
    elif action == "stop-test":
        base.stop_test()
    else:
        install(action)

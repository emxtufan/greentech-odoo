"""Back up the finance database, test on a clone and install without financial changes."""
import argparse
import json
import subprocess
import d112_deploy as base

base.WORK = base.ROOT / "logs/tbs-modules-20261020"
MODULE = "tbs_saft_d406,tbs_anaf_duk_validator,l10n_ro_edi_stock_extension,greentech_tbs_integration"


def configure_background_jobs(config):
    # The newly required payment addon creates an active post-processing job.
    # Keep the finance instance's established manual-only operating mode.
    code = """
job = env.ref('payment.cron_post_process_payment_tx', raise_if_not_found=False)
if job:
    job.write({'active': False})
env.cr.commit()
print('TBS_BACKGROUND_JOBS_CONFIGURED')
"""
    result = subprocess.run([str(base.PYTHON), str(base.ODOO), "shell", "-c", str(config), "--no-http"],
                            input=code, text=True, encoding="utf-8", cwd=base.ROOT, env=base.ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert result.returncode == 0 and "TBS_BACKGROUND_JOBS_CONFIGURED" in result.stdout, result.stdout[-2000:]


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
        cur.execute("SELECT name, state FROM ir_module_module WHERE name = ANY(%s)", (MODULE.split(','),))
        states = dict(cur.fetchall())
    new = [m for m in MODULE.split(",") if states.get(m) != "installed"]
    updates = [m for m in MODULE.split(",") if states.get(m) == "installed"]
    if target == "test":
        updates += ["greentech_anaf_d300", "greentech_ro_vat_journals", "greentech_ro_advances"]
    log = base.WORK / f"{target}-install.log"
    if log.exists():
        log.rename(base.WORK / f"{target}-install-{len(list(base.WORK.glob('*install*.log')))}.log")
    cmd = [str(base.PYTHON), str(base.ODOO), "-c", str(config), "--no-http", "--stop-after-init",
           "--without-demo", "--logfile", str(log)]
    if new:
        cmd += ["-i", ",".join(new)]
    if updates:
        cmd += ["-u", ",".join(updates)]
    if target == "test":
        cmd += ["--test-enable", "--test-tags", "/" + MODULE.replace(",", ",/") + ",/greentech_anaf_d300,/greentech_ro_vat_journals,/greentech_ro_advances"]
    result = subprocess.run(cmd, cwd=base.ROOT, env=base.ENV, capture_output=True)
    (base.WORK / f"{target}-console.log").write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, "Inspect install log"
    if target == "test":
        assert "0 failed, 0 error(s)" in log.read_text(encoding="utf-8"), "Tests failed"
    configure_background_jobs(config)
    current = base.snapshot(opts)
    for key in ("moves", "lines", "payments", "unbalanced_posted"):
        assert current[key] == before[key], "Accounting changed: " + key
    assert current["active_cron"] == 0
    assert all(m in current["installed"] for m in MODULE.split(","))
    base.save_json(base.WORK / f"{target}-verified.json", current)
    print("TBS_INSTALLED_ACCOUNTING_UNCHANGED", target)
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

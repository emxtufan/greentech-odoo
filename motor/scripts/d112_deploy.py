"""Install D112 after isolated tests; retain backups and compare accounting hashes."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from zipfile import ZipFile

import psutil
from psycopg2 import sql
from ro_oca_install import ROOT, LIVE, PG, read_config, connection, snapshot, save_json

WORK = ROOT / "logs/d112-install-20261020"
PYTHON = ROOT / ".venv/Scripts/python.exe"
ODOO = ROOT / "odoo/odoo-bin"
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")


def stop_finance():
    pidfile = ROOT / "logs/financial-server.pid"
    pid = int(pidfile.read_text().strip())
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    command = process.cmdline()
    if "-c" not in command:
        raise RuntimeError("Recorded PID is not an Odoo configuration process")
    config = Path(command[command.index("-c") + 1])
    if not config.is_absolute():
        config = Path(process.cwd()) / config
    if config.resolve() != LIVE.resolve() or not any("odoo-bin" in s for s in command):
        raise RuntimeError("Refusing to stop an unrelated process")
    processes = process.children(recursive=True) + [process]
    for child in processes:
        child.terminate()
    _, alive = psutil.wait_procs(processes, timeout=8)
    if alive:
        raise RuntimeError("Financial process did not stop")
    print("D112_FINANCIAL_SERVER_STOPPED")


def stop_test():
    pidfile = WORK / "server.pid"
    if not pidfile.exists():
        return
    try:
        process = psutil.Process(int(pidfile.read_text()))
    except psutil.NoSuchProcess:
        return
    command = process.cmdline()
    assert "-c" in command and any("odoo-bin" in arg for arg in command)
    config = Path(command[command.index("-c") + 1])
    if not config.is_absolute():
        config = Path(process.cwd()) / config
    assert config.resolve() == (WORK / "test.conf").resolve()
    processes = process.children(recursive=True) + [process]
    for child in processes:
        child.terminate()
    assert not psutil.wait_procs(processes, timeout=8)[1]


def start_test():
    with (WORK / "server-out.log").open("ab") as out, (WORK / "server-error.log").open("ab") as err:
        process = subprocess.Popen([str(PYTHON), str(ODOO), "-c", str(WORK / "test.conf")],
                                   cwd=ROOT, env=ENV, stdout=out, stderr=err,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    (WORK / "server.pid").write_text(str(process.pid))


def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    if (WORK / "state.json").exists():
        raise RuntimeError("A test copy already exists; reuse its recorded config.")
    opts = read_config()["options"]
    assert opts["db_name"] == "greentech_financiar_test"
    stop_finance()
    before = snapshot(opts)
    save_json(WORK / "before.json", before)
    subprocess.run([str(PYTHON), str(ROOT / "scripts/financial_backup.py")], check=True, cwd=ROOT, env=ENV)
    backup = json.loads((ROOT / "logs/financial-backup.json").read_text())
    dump = WORK / "before.dump"
    with ZipFile(backup["path"]) as archive:
        dump.write_bytes(archive.read("database.dump"))
    db = "gt_d112_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    con = connection(opts, "postgres")
    try:
        con.autocommit = True
        with con.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template1").format(sql.Identifier(db)))
    finally:
        con.close()
    subprocess.run([str(PG / "pg_restore.exe"), "-h", opts["db_host"], "-p", opts["db_port"],
                    "-U", opts["db_user"], "--exit-on-error", "--single-transaction",
                    "--no-owner", "--no-privileges", "-d", db, str(dump)],
                   env=dict(ENV, PGPASSWORD=opts["db_password"]), capture_output=True, check=True)
    filestore = Path(opts["data_dir"]) / "filestore" / opts["db_name"]
    if filestore.exists():
        shutil.copytree(filestore, WORK / "test-data/filestore" / db)
    cfg = read_config()
    cfg["options"].update(db_name=db, dbfilter="^" + db + "$", data_dir=str(WORK / "test-data"),
                          logfile=str(WORK / "test.log"), http_port="8072", max_cron_threads="0")
    with (WORK / "test.conf").open("w", encoding="utf-8") as out:
        cfg.write(out)
    assert snapshot(cfg["options"]) == before
    save_json(WORK / "state.json", {"database": db, "backup": backup["path"], "config": str(WORK / "test.conf")})
    print("D112_TEST_COPY_READY", db)


def configure(config):
    code = """
from odoo import Command
from odoo.addons.greentech_anaf_d112.services import duk
from pathlib import Path
root = Path.cwd()
env.ref('base.user_admin').write({'group_ids': [Command.link(env.ref('greentech_anaf_d112.group_anaf').id)]})
env['ir.config_parameter'].sudo().set_param('gt_anaf.duk_dir', str(root / 'tools/anaf/duk'))
env.cr.commit()
print('D112_ADMIN_ACCESS_CONFIGURED')
print('D112_RUNTIME_STATUS', duk.readiness(str(root / 'tools/anaf/duk'))[1])
"""
    result = subprocess.run([str(PYTHON), str(ODOO), "shell", "-c", str(config), "--no-http"],
                            input=code, text=True, encoding="utf-8", env=ENV, cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (WORK / ("configure-live.log" if config == LIVE else "configure-test.log")).write_text(result.stdout, encoding="utf-8")
    if result.returncode or "D112_ADMIN_ACCESS_CONFIGURED" not in result.stdout:
        raise RuntimeError("Configuration failed; inspect configure log")
    print("D112_ACCESS_AND_VALIDATOR_PATH_CONFIGURED")


def check(target):
    config = LIVE if target == "live" else WORK / "test.conf"
    current = snapshot(read_config(config)["options"])
    before = json.loads((WORK / "before.json").read_text())
    for key in ("moves", "lines", "payments", "unbalanced_posted", "active_cron"):
        assert current[key] == before[key], "Changed financial data: " + key
    assert "greentech_anaf_d112" in current["installed"]
    save_json(WORK / (target + "-verified.json"), current)
    print("D112_ACCOUNTING_UNCHANGED", target)


def install(target):
    config = LIVE if target == "live" else WORK / "test.conf"
    if target == "live":
        assert (WORK / "test-verified.json").is_file()
        assert (WORK / "browser-test.json").is_file()
        browser = json.loads((WORK / "browser-test.json").read_text())
        assert browser["status"] == "passed"
        stop_finance()
        current = snapshot(read_config()["options"])
        before = json.loads((WORK / "before.json").read_text())
        assert current == before, "Live changed since backup; take new backup before installing."
    command = [str(PYTHON), str(ODOO), "-c", str(config), "--no-http", "--stop-after-init",
               "--without-demo", "-i" if target == "live" else "-u", "greentech_anaf_d112",
               "--logfile", str(WORK / (target + "-install.log"))]
    if target == "test":
        opts = read_config(config)["options"]
        with connection(opts) as con, con.cursor() as cur:
            cur.execute("SELECT state FROM ir_module_module WHERE name='greentech_anaf_d112'")
            row = cur.fetchone()
        if not row or row[0] == "uninstalled":
            command[command.index("-u")] = "-i"
        command.extend(["--test-enable", "--test-tags", "/greentech_anaf_d112"])
    result = subprocess.run(command, cwd=ROOT, env=ENV, capture_output=True)
    (WORK / (target + "-console.log")).write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("Install/tests failed; inspect " + str(WORK / (target + "-install.log")))
    if target == "test":
        log = (WORK / "test-install.log").read_text(encoding="utf-8")
        assert "0 failed, 0 error(s)" in log, "No successful Odoo test result found"
    configure(config)
    check(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "test", "live", "check-live", "stop", "refresh-test", "stop-test"])
    action = parser.parse_args().action
    if action == "prepare":
        prepare()
    elif action == "check-live":
        check("live")
    elif action == "stop":
        stop_finance()
    elif action == "stop-test":
        stop_test()
    elif action == "refresh-test":
        stop_test()
        install("test")
        start_test()
    else:
        install(action)

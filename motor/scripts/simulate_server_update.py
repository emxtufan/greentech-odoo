"""Exercise the server module update against an isolated copy of the old demo.

Never changes greentech_financiar_test. The temporary database and filestore
are removed after the Odoo install attempt; logs remain for diagnosis.
"""

import configparser
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "logs/server-transfer/20261019-140807/greentech-financiar"
UPDATE = ROOT / "logs/server-transfer/current-addons-20261020/greentech-financiar-update-20261020.zip"
with __import__("zipfile").ZipFile(UPDATE) as archive:
    update = json.loads(archive.read("manifest.json"))
modules = update["install_modules"]

config = configparser.RawConfigParser()
config.read(ROOT / "config/odoo-financiar.conf", encoding="utf-8")
options = config["options"]
credentials = dict(host=options["db_host"], port=options["db_port"],
                   user=options["db_user"], password=options["db_password"])
db = "gt_update_probe_" + datetime.now().strftime("%Y%m%d_%H%M%S")
out = ROOT / "logs/server-transfer" / db
out.mkdir(parents=True, exist_ok=False)
data_dir = out / "data"
filestore = data_dir / "filestore" / db
database_created = False
connection = psycopg2.connect(dbname="postgres", **credentials)
connection.autocommit = True
try:
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(db)))
    database_created = True

    pg_restore = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
    restored = subprocess.run([str(pg_restore), "--exit-on-error", "--single-transaction",
        "--no-owner", "--no-privileges", "-h", options["db_host"], "-p", options["db_port"],
        "-U", options["db_user"], "-d", db, str(OLD / "backup/database.dump")],
        env=dict(os.environ, PGPASSWORD=options["db_password"]),
        stdout=out.joinpath("restore.stdout").open("w", encoding="utf-8"),
        stderr=out.joinpath("restore.stderr").open("w", encoding="utf-8"))
    if restored.returncode:
        raise RuntimeError("Old server snapshot restore failed; inspect restore.stderr")

    shutil.copytree(OLD / "backup/filestore", filestore)
    options["db_name"] = db
    options["dbfilter"] = "^" + db + "$"
    options["data_dir"] = str(data_dir)
    options["logfile"] = str(out / "odoo.log")
    options["max_cron_threads"] = "0"
    test_config = out / "odoo.conf"
    with test_config.open("w", encoding="utf-8") as stream:
        config.write(stream)
    try:
        command = [str(ROOT / ".venv/Scripts/python.exe"), str(ROOT / "odoo/odoo-bin"),
                   "-c", str(test_config), "-d", db, "--no-http", "--stop-after-init",
                   "-i", ",".join(modules)]
        with (out / "install.stdout").open("w", encoding="utf-8") as stdout, \
             (out / "install.stderr").open("w", encoding="utf-8") as stderr:
            installed = subprocess.run(command, stdout=stdout, stderr=stderr,
                                       timeout=1800, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        if installed.returncode:
            raise RuntimeError(f"Odoo install failed ({installed.returncode}); inspect {out / 'odoo.log'}")
        with psycopg2.connect(dbname=db, **credentials) as test:
            with test.cursor() as cursor:
                cursor.execute("SELECT name FROM ir_module_module WHERE state='installed'")
                names = {row[0] for row in cursor.fetchall()}
                missing = sorted(set(modules) - names)
                cursor.execute("SELECT count(*) FROM account_move")
                moves = cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM account_move_line")
                lines = cursor.fetchone()[0]
        if missing:
            raise RuntimeError("Missing installed modules: " + ", ".join(missing))
        report = {"result": "ok", "installed_modules": len(names), "new_modules": len(modules),
                  "journal_entries": moves, "move_lines": lines, "log_dir": str(out)}
        (out / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    finally:
        test_config.unlink(missing_ok=True)
finally:
    if database_created:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db)))
    connection.close()
    if data_dir.is_dir() and data_dir.is_relative_to(out):
        shutil.rmtree(data_dir)

"""Pinned OCA sources, isolated installation, and accounting integrity checks."""
import argparse
import ast
import base64
import configparser
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "logs/oca-ro-install-20261020"
LIVE = ROOT / "config/odoo-financiar.conf"
PG = Path(r"C:\Program Files\PostgreSQL\18\bin")


def read_config(path=LIVE):
    cfg = configparser.RawConfigParser()
    cfg.read(path, encoding="utf-8")
    return cfg


def connection(opts, db=None):
    return psycopg2.connect(
        host=opts["db_host"], port=opts["db_port"], user=opts["db_user"],
        password=opts["db_password"], dbname=db or opts["db_name"],
    )


def snapshot(opts):
    result = {}
    with connection(opts) as con, con.cursor() as cur:
        for label, query in {
            "moves": "SELECT id,name,date,company_id,state,move_type,amount_total,amount_untaxed,amount_tax,currency_id,partner_id,ref FROM account_move ORDER BY id",
            "lines": "SELECT id,move_id,account_id,partner_id,debit,credit,balance,amount_currency,currency_id,company_id,date FROM account_move_line ORDER BY id",
            "payments": "SELECT id,amount,date,company_id,currency_id,partner_id,state FROM account_payment ORDER BY id",
        }.items():
            cur.execute(query)
            rows = cur.fetchall()
            data = json.dumps(rows, default=str, ensure_ascii=False).encode()
            result[label] = {"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()}
        cur.execute("SELECT count(*) FROM (SELECT m.id FROM account_move m JOIN account_move_line l ON l.move_id=m.id WHERE m.state='posted' GROUP BY m.id HAVING abs(sum(l.balance))>0.005) q")
        result["unbalanced_posted"] = cur.fetchone()[0]
        cur.execute("SELECT name,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name")
        result["installed"] = dict(cur.fetchall())
        cur.execute("SELECT count(*) FROM ir_cron WHERE active")
        result["active_cron"] = cur.fetchone()[0]
    return result


def save_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def sources():
    count = 0
    provenance = []
    for bundle in sorted((WORK / "sources").glob("*.json")):
        for item in json.loads(bundle.read_text(encoding="utf-8")):
            raw = base64.b64decode(item["content"]) if item["encoding"] == "base64" else item["content"].encode("utf-8")
            digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if digest != item["sha"] or digest != item["tree_sha"]:
                raise RuntimeError("Git integrity mismatch: " + item["path"])
            base = ROOT / "third_party_addons" / item["destination"]
            target = (base / item["path"]).resolve()
            if not target.is_relative_to(base.resolve()):
                raise RuntimeError("Invalid source path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            provenance.append({k: item[k] for k in ("repository", "ref", "path", "sha", "destination")})
            count += 1
    save_json(WORK / "source-lock.json", provenance)
    print("OCA_SOURCE_FILES_VERIFIED", count)


def prepare():
    if (WORK / "state.json").exists():
        raise RuntimeError("Test copy already prepared; use recorded state")
    cfg = read_config()
    opts = cfg["options"]
    assert opts["db_name"] == "greentech_financiar_test"
    before = snapshot(opts)
    save_json(WORK / "before.json", before)
    shutil.copy2(LIVE, WORK / "original.conf")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db = "gt_oca_ro_" + stamp
    dump = WORK / "before.dump"
    args = ["-h", opts["db_host"], "-p", opts["db_port"], "-U", opts["db_user"]]
    env = dict(os.environ, PGPASSWORD=opts["db_password"])
    subprocess.run([str(PG / "pg_dump.exe"), *args, "-Fc", "-f", str(dump), opts["db_name"]], env=env, check=True, capture_output=True)
    subprocess.run([str(PG / "pg_restore.exe"), "--list", str(dump)], check=True, capture_output=True)
    con = connection(opts, "postgres")
    try:
        con.autocommit = True
        with con.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template1").format(sql.Identifier(db)))
    finally:
        con.close()
    original_fs = Path(opts["data_dir"]) / "filestore" / opts["db_name"]
    if original_fs.exists():
        shutil.copytree(original_fs, WORK / "filestore-backup")
        shutil.copytree(original_fs, WORK / "test-data/filestore" / db)
    subprocess.run([str(PG / "pg_restore.exe"), *args, "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges", "-d", db, str(dump)], env=env, check=True, capture_output=True)
    paths = [str(ROOT / "third_party_addons/oca-ro-19") if Path(p.strip()).name == "l10n-romania" else p.strip()
             for p in opts["addons_path"].split(",")]
    paths.append(str(ROOT / "third_party_addons/bank-statement-import"))
    opts["addons_path"] = ",".join(paths)
    with (WORK / "candidate-live.conf").open("w", encoding="utf-8") as out:
        cfg.write(out)
    opts.update(db_name=db, dbfilter="^" + db + "$", data_dir=str(WORK / "test-data"),
                logfile=str(WORK / "test-odoo.log"), max_cron_threads="0",
                http_enable="False", http_port="8071")
    with (WORK / "test.conf").open("w", encoding="utf-8") as out:
        cfg.write(out)
    save_json(WORK / "state.json", {"database": db, "config": str(WORK / "test.conf"), "dump": str(dump)})
    cloned = snapshot(opts)
    assert cloned == before, "Clone differs from source"
    print("OCA_BACKUP_AND_TEST_COPY_READY", db, dump.stat().st_size)


def check(target):
    opts = read_config(WORK / "test.conf" if target == "test" else LIVE)["options"]
    current = snapshot(opts)
    before = json.loads((WORK / "before.json").read_text(encoding="utf-8"))
    for key in ("moves", "lines", "payments", "unbalanced_posted"):
        if current[key] != before[key]:
            raise RuntimeError("Accounting data changed: " + key)
    requested = json.loads((WORK / "selection.json").read_text(encoding="utf-8"))["modules"]
    missing = sorted(set(requested) - current["installed"].keys())
    if missing:
        raise RuntimeError("Not installed: " + ",".join(missing))
    assert current["active_cron"] == 0, "Scheduled integrations must remain inactive"
    current["new_modules"] = sorted(set(current["installed"]) - before["installed"].keys())
    save_json(WORK / (target + "-verified.json"), current)
    print("OCA_INSTALL_VERIFIED", target, len(current["new_modules"]), "new modules; accounting unchanged")


def preflight():
    cfg = read_config(WORK / "test.conf")["options"]
    available = {}
    for p in cfg["addons_path"].split(","):
        for manifest in Path(p.strip()).glob("*/__manifest__.py"):
            spec = ast.literal_eval(manifest.read_text(encoding="utf-8-sig"))
            available[manifest.parent.name] = spec
    selected = json.loads((WORK / "selection.json").read_text(encoding="utf-8"))["modules"]
    visited = set()

    def visit(name):
        if name in visited:
            return
        if name not in available:
            raise RuntimeError("Missing addon: " + name)
        visited.add(name)
        spec = available[name]
        if not spec.get("installable", True):
            raise RuntimeError("Uninstallable addon: " + name)
        for dep in spec.get("depends", []):
            visit(dep)

    for name in selected:
        visit(name)
    save_json(WORK / "dependency-closure.json", sorted(visited))
    print("OCA_DEPENDENCIES_PRESENT", len(visited))


def install(target):
    config = WORK / "test.conf" if target == "test" else LIVE
    opts = read_config(config)["options"]
    if target == "live":
        assert (WORK / "test-verified.json").exists(), "Verify the test copy first"
        assert opts["db_name"] == "greentech_financiar_test"
    selected = json.loads((WORK / "selection.json").read_text(encoding="utf-8"))["modules"]
    result = subprocess.run(
        [str(ROOT / ".venv/Scripts/python.exe"), str(ROOT / "odoo/odoo-bin"),
         "-c", str(config), "--no-http", "--stop-after-init", "--without-demo",
         "-i", ",".join(selected), "-u", "l10n_ro_config,l10n_ro_account,l10n_ro_account_period_close"],
        cwd=ROOT, check=False, env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
    )
    # No scheduler runs during installation. Preserve the disabled integration
    # state for newly introduced scheduled actions, too.
    with connection(opts) as con, con.cursor() as cur:
        cur.execute("UPDATE ir_cron SET active=false WHERE active")
    if result.returncode:
        raise SystemExit(result.returncode)
    print("OCA_MODULE_LOAD_FINISHED", target)


def activate():
    assert (WORK / "test-verified.json").exists(), "Verify test installation first"
    assert json.loads((WORK / "smoke.json").read_text())["status"] == "passed"
    opts = read_config()["options"]
    with socket.socket() as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", int(opts["http_port"]))) == 0:
            raise RuntimeError("Stop the financial server before activating")
    before = json.loads((WORK / "before.json").read_text())
    assert snapshot(opts) == before, "Source changed since backup; take a new backup"
    shutil.copy2(WORK / "candidate-live.conf", LIVE)
    print("OCA_LIVE_CONFIG_ACTIVATED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["sources", "prepare", "preflight", "test", "live", "install-test", "install-live", "activate"])
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    if args.action.startswith("install-"):
        install(args.action.split("-")[1])
    elif args.action in ("test", "live"):
        check(args.action)
    else:
        globals()[args.action]()

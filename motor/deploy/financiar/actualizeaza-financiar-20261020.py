"""Upgrade the existing GreenTech Financiar demo through a verified DB clone.

Run on greentech-app as root with --check, then --install. The original database,
filestore, and changed addon directories are retained for rollback.
"""

import argparse
import configparser
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import grp
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
from zipfile import ZipFile


ROOT = Path("/opt/greentech-financiar")
ADDONS = ROOT / "addons"
DATA = Path("/var/lib/greentech-financiar")
DB = "greentech_financiar_test"
ROLE = "gt_financiar"
SERVICE = "greentech-financiar.service"
CONF = Path("/etc/greentech-financiar/odoo.conf")
ODOO = ROOT / "source/odoo-bin"
PYTHON = ROOT / "venv/bin/python"
ARCHIVE = Path("/tmp/greentech-financiar-update-20261020.zip")
ARCHIVE_SHA = "e95b7493a15242d24fb88f77c7504f143449403b1e20124867ca3cdcbfc989cc"
FILEROOT = DATA / "filestore"


def run(args, *, capture=False, **kwargs):
    result = subprocess.run([str(a) for a in args], text=True, check=True,
                            capture_output=capture, **kwargs)
    return result.stdout.strip() if capture else ""


def postgres(query, database="postgres"):
    return run(["runuser", "-u", "postgres", "--", "psql", "-X", "-A", "-t",
                "-d", database, "-c", query], capture=True)


def modules(database):
    return set(postgres("SELECT name FROM ir_module_module WHERE state='installed'", database).splitlines())


def accounting_snapshot(database):
    return postgres("""SELECT
        (SELECT count(*) FROM account_move),
        (SELECT count(*) FROM account_move_line),
        (SELECT count(*) FROM account_payment),
        (SELECT coalesce(sum(debit),0) FROM account_move_line),
        (SELECT coalesce(sum(credit),0) FROM account_move_line)""", database)


def verify_archive():
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    if digest != ARCHIVE_SHA:
        raise RuntimeError("Arhiva nu corespunde SHA256 asteptat: " + digest)
    with ZipFile(ARCHIVE) as archive:
        files = set(archive.namelist())
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (not entry.filename or "\\" in entry.filename or path.is_absolute()
                    or ".." in path.parts or stat.S_ISLNK(entry.external_attr >> 16)):
                raise RuntimeError("Cale ZIP nesigura: " + entry.filename)
        checks = archive.read("SHA256SUMS").decode("utf-8").splitlines()
        if len(checks) + 1 != len(files):
            raise RuntimeError("Lista SHA256SUMS nu acopera toate fisierele")
        for line in checks:
            expected, name = line.split("  ", 1)
            if name not in files or hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise RuntimeError("Fisier invalid in arhiva: " + name)
        manifest = json.loads(archive.read("manifest.json"))
        if manifest["database"] != DB or len(manifest["install_modules"]) != 75:
            raise RuntimeError("Manifestul nu corespunde actualizarii pregatite")
        for name in manifest["install_modules"]:
            if f"addons/{name}/__manifest__.py" not in files:
                raise RuntimeError("Lipseste modulul " + name)
    return manifest


def preflight():
    if not sys.platform.startswith("linux") or os.geteuid() != 0:
        raise RuntimeError("Ruleaza pe serverul Linux, ca root")
    for path in (ROOT, ADDONS, DATA, CONF, ODOO, PYTHON, ARCHIVE, FILEROOT / DB):
        if not path.exists():
            raise RuntimeError("Lipseste: " + str(path))
    options = configparser.RawConfigParser()
    options.read(CONF, encoding="utf-8")
    cfg = options["options"]
    if (cfg.get("db_name") != DB or cfg.get("data_dir") != str(DATA)
            or str(ADDONS) not in cfg.get("addons_path", "")):
        raise RuntimeError("Configuratia Odoo nu corespunde acestui server")
    if run(["systemctl", "is-active", SERVICE], capture=True) != "active":
        raise RuntimeError("Serviciul Odoo trebuie sa fie pornit la inceput")
    run(["java", "-version"], capture=True)
    run(["runuser", "-u", ROLE, "--", PYTHON, "-c",
         "import lxml, pypdf, reportlab, num2words, openpyxl"], capture=True)
    manifest = verify_archive()
    current = modules(DB)
    packaged = set(manifest["install_modules"])
    for name, details in manifest["package_modules"].items():
        missing = set(details["depends"]) - current - packaged
        if missing:
            raise RuntimeError(f"Dependinte indisponibile pentru {name}: {sorted(missing)}")
    free = min(shutil.disk_usage(ROOT).free, shutil.disk_usage(DATA).free)
    if free < 1_000_000_000:
        raise RuntimeError("Spatiu liber sub 1 GB; nu incep actualizarea")
    print(json.dumps({"service": "active", "server_installed": len(current),
                      "new_to_install": len(packaged - current),
                      "already_installed_to_upgrade": len(packaged & current),
                      "accounting_snapshot": accounting_snapshot(DB),
                      "available_gb": round(free / 1e9, 2)}, indent=2), flush=True)
    return manifest, current, options


def chown_tree(folder, user, group):
    uid = pwd.getpwnam(user).pw_uid
    gid = grp.getgrnam(group).gr_gid
    os.chown(folder, uid, gid)
    folder.chmod(0o750)
    for path in folder.rglob("*"):
        os.chown(path, uid, gid)
        path.chmod(0o750 if path.is_dir() else 0o640)


def restore_code(changed):
    for target, previous in reversed(changed):
        if target.is_dir():
            shutil.rmtree(target)
        if previous is not None and previous.exists():
            previous.rename(target)


def healthy():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if subprocess.run(["systemctl", "is-active", "--quiet", SERVICE]).returncode == 0:
            try:
                with urllib.request.urlopen("http://127.0.0.1:8070/odoo", timeout=5) as response:
                    if response.status < 500:
                        return True
            except Exception:
                pass
        time.sleep(3)
    return False


def install(manifest, current, config):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = ROOT / ".updates" / stamp
    backup = Path("/var/backups") / ("greentech-financiar-update-" + stamp)
    stage = work / "stage"
    work.mkdir(parents=True, mode=0o700)
    backup.mkdir(parents=True, mode=0o700)
    with ZipFile(ARCHIVE) as archive:
        archive.extractall(stage)
    (backup / "before.json").write_text(json.dumps({
        "installed_modules": sorted(current), "accounting_snapshot": accounting_snapshot(DB),
        "archive_sha256": ARCHIVE_SHA}, indent=2), encoding="utf-8")
    changed = []
    tempdb = "gt_anaf_trial_" + datetime.now().strftime("%m%d%H%M%S")
    beforedb = "gt_anaf_before_" + datetime.now().strftime("%m%d%H%M%S")
    faileddb = "gt_anaf_failed_" + datetime.now().strftime("%m%d%H%M%S")
    original_fs = FILEROOT / DB
    trial_fs = FILEROOT / tempdb
    before_fs = FILEROOT / beforedb
    failed_fs = FILEROOT / faileddb
    trial_conf_dir = DATA / (".anaf-update-" + stamp)
    trial_conf = trial_conf_dir / "odoo.conf"
    trial_created = False
    original_renamed = False
    trial_promoted = False
    original_fs_renamed = False
    trial_fs_promoted = False
    promoted = False
    print("Backup:", backup, flush=True)
    run(["systemctl", "stop", SERVICE])
    try:
        dump_tmp = Path("/tmp") / ("gt-anaf-" + stamp + ".dump")
        run(["runuser", "-u", "postgres", "--", "pg_dump", "-Fc", "-f", dump_tmp, DB])
        run(["pg_restore", "--list", dump_tmp], capture=True)
        shutil.copy2(dump_tmp, backup / "database.dump")
        (backup / "database.dump").chmod(0o600)
        dump_tmp.unlink()
        run(["tar", "-czf", backup / "filestore.tar.gz", "-C", FILEROOT, DB])
        run(["tar", "-tzf", backup / "filestore.tar.gz"], capture=True)

        for name in manifest["install_modules"]:
            source = stage / "addons" / name
            target = ADDONS / name
            previous = work / "previous-addons" / name if target.exists() else None
            if previous:
                previous.parent.mkdir(parents=True, exist_ok=True)
                target.rename(previous)
            changed.append((target, previous))
            shutil.copytree(source, target)
            chown_tree(target, "root", ROLE)
        for folder in ("duk", "d300", "d406"):
            source = stage / "tools/anaf" / folder
            target = ROOT / "tools/anaf" / folder
            target.parent.mkdir(parents=True, exist_ok=True)
            previous = work / "previous-tools" / folder if target.exists() else None
            if previous:
                previous.parent.mkdir(parents=True, exist_ok=True)
                target.rename(previous)
            changed.append((target, previous))
            shutil.copytree(source, target)
            chown_tree(target, "root", ROLE)

        # Upgrade a clone. The original DB and filestore remain untouched.
        postgres(f"CREATE DATABASE {tempdb} WITH TEMPLATE {DB} OWNER {ROLE}")
        trial_created = True
        shutil.copytree(original_fs, trial_fs)
        chown_tree(trial_fs, ROLE, ROLE)
        trial_conf_dir.mkdir(mode=0o700)
        chown_tree(trial_conf_dir, ROLE, ROLE)
        config["options"]["db_name"] = tempdb
        config["options"]["dbfilter"] = "^" + tempdb + "$"
        config["options"]["max_cron_threads"] = "0"
        config["options"]["logfile"] = str(trial_conf_dir / "odoo.log")
        with trial_conf.open("w", encoding="utf-8") as stream:
            config.write(stream)
        trial_conf.chmod(0o600)
        os.chown(trial_conf, pwd.getpwnam(ROLE).pw_uid, grp.getgrnam(ROLE).gr_gid)
        command = ["runuser", "-u", ROLE, "--", PYTHON, ODOO, "-c", trial_conf,
                   "-d", tempdb, "--no-http", "--stop-after-init"]
        missing = sorted(set(manifest["install_modules"]) - current)
        existing = sorted(set(manifest["install_modules"]) & current)
        if missing:
            command += ["-i", ",".join(missing)]
        if existing:
            command += ["-u", ",".join(existing)]
        with (backup / "odoo-upgrade.stdout").open("w", encoding="utf-8") as out, \
             (backup / "odoo-upgrade.stderr").open("w", encoding="utf-8") as err:
            result = subprocess.run([str(x) for x in command], cwd=ROOT / "source",
                                    stdout=out, stderr=err, timeout=1800)
        if result.returncode:
            raise RuntimeError("Upgrade-ul bazei de proba a esuat; vezi odoo-upgrade.stderr si odoo.log")
        missing_after = set(manifest["install_modules"]) - modules(tempdb)
        if missing_after:
            raise RuntimeError("Module neinstalate: " + ", ".join(sorted(missing_after)))
        if accounting_snapshot(tempdb) != accounting_snapshot(DB):
            raise RuntimeError("Datele contabile s-au schimbat in baza de proba")

        # Promote only the proven clone, retaining the old DB and filestore.
        postgres(f"ALTER DATABASE {DB} RENAME TO {beforedb}")
        original_renamed = True
        postgres(f"ALTER DATABASE {tempdb} RENAME TO {DB}")
        trial_promoted = True
        original_fs.rename(before_fs)
        original_fs_renamed = True
        trial_fs.rename(original_fs)
        trial_fs_promoted = True
        run(["systemctl", "start", SERVICE])
        if not healthy():
            raise RuntimeError("Odoo nu raspunde dupa pornire")
        promoted = True
        (backup / "result.json").write_text(json.dumps({
            "status": "installed", "installed_modules": len(modules(DB)),
            "old_database": beforedb, "old_filestore": str(before_fs),
            "accounting_snapshot": accounting_snapshot(DB)}, indent=2), encoding="utf-8")
        print("UPDATE_OK", backup, flush=True)
    except BaseException:
        run(["systemctl", "stop", SERVICE])
        if trial_fs_promoted and original_fs.exists():
            original_fs.rename(failed_fs)
        if original_fs_renamed and before_fs.exists():
            before_fs.rename(original_fs)
        if trial_promoted:
            postgres(f"ALTER DATABASE {DB} RENAME TO {faileddb}")
        if original_renamed:
            postgres(f"ALTER DATABASE {beforedb} RENAME TO {DB}")
        restore_code(changed)
        run(["systemctl", "start", SERVICE])
        print("UPDATE_FAILED_ROLLED_BACK; see", backup, flush=True)
        raise
    finally:
        trial_conf.unlink(missing_ok=True)
        if promoted and trial_conf_dir.exists():
            shutil.rmtree(trial_conf_dir)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    if args.check == args.install:
        parser.error("Alegeti --check sau --install")
    manifest, current, config = preflight()
    if args.install:
        install(manifest, current, config)
    else:
        print("PREFLIGHT_OK", flush=True)


if __name__ == "__main__":
    main()

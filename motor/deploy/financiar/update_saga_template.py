#!/usr/bin/env python3
"""One-time native addon deployment. Embedded payload is code + synthetic reader test only."""
import argparse
import base64
import configparser
from datetime import datetime, timezone
import grp
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

PAYLOAD_B64 = '__PAYLOAD__'
PAYLOAD_SHA256 = '__PAYLOAD_SHA256__'
ROOT = Path('/opt/greentech-financiar')
DATA = Path('/var/lib/greentech-financiar')
CONF = Path('/etc/greentech-financiar/odoo.conf')
MODULE = 'greentech_saga_import'
SERVICE = 'greentech-financiar.service'
PYTHON = ROOT/'venv/bin/python'
RELEASE = 'saga-engine12-path-20261019-2'


def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args],text=True,capture_output=True,**kwargs)
    if result.returncode:
        raise RuntimeError('Comanda a esuat: '+str(args[0])+'\n'+result.stderr[-3000:])
    return result.stdout


def require(condition,message):
    if not condition:
        raise RuntimeError(message)


def owner_tree(path,uid,gid):
    for item in [path,*path.rglob('*')]:
        if item.is_symlink():
            continue
        os.chown(item,uid,gid)
        item.chmod(0o750 if item.is_dir() else 0o640)


def install_reader_driver():
    # The parent uses 0077 to protect backups/configuration. Python packages,
    # however, must be readable by the unprivileged Odoo service. Reinstall the
    # two reader dependencies from a fresh cache, so a previous root-only
    # installation cannot be silently reused. Preserve six's installed version.
    six_version = run([PYTHON, '-I', '-c',
        "import importlib.metadata as m; print(m.version('six'))"]).strip()
    require(bool(re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', six_version)),
            'Versiunea six nu a putut fi identificata; mediul Odoo nu este modificat.')
    run([ROOT/'bootstrap/bin/python', '-m', 'uv', 'pip', 'install', '--python', PYTHON,
         '--no-cache', '--link-mode', 'copy', '--reinstall-package', 'fdb',
         '--reinstall-package', 'six', 'fdb==2.0.4', 'six==' + six_version],
        env=dict(os.environ, UV_CACHE_DIR=str(ROOT/'.uv-cache')), umask=0o022)
    probe = """import fdb, inspect, json, sys
from pathlib import Path
from importlib.metadata import version
origin = getattr(fdb, '__file__', None)
assert origin and callable(getattr(fdb, 'connect', None)), 'FDB_INVALID: origin=' + repr(origin) + '; paths=' + repr(list(getattr(fdb, '__path__', [])))
assert Path(origin).resolve().is_relative_to(Path(sys.prefix).resolve()), 'FDB incarcat din afara mediului financiar: ' + origin
assert version('fdb') == '2.0.4', 'Versiune fdb neasteptata'
assert {'no_gc', 'no_db_triggers', 'no_linger', 'utf8params'} <= set(inspect.signature(fdb.connect).parameters), 'Interfata fdb.connect incompatibila'
print(json.dumps({'module': origin, 'version': version('fdb'), 'connect': True}))
"""
    result = run(['runuser', '-u', 'gt_financiar', '--', PYTHON, '-I', '-c', probe],
                 cwd=DATA, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', HOME=str(DATA)))
    print('SAGA_FDB_IMPORT_OK: ' + result.strip(), flush=True)


def copy_runtime_file(source, destination, runtime):
    """Copy to our private runtime atomically; never chmod/overwrite a system target."""
    source = source.resolve(strict=True)
    require(source.is_file(), 'Lipseste fisierul Firebird: ' + str(source))
    require(destination.parent.resolve().is_relative_to(runtime.resolve()), 'Cale runtime neasteptata.')
    destination.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    require(destination.parent.resolve().is_relative_to(runtime.resolve()), 'Cale runtime neasteptata.')
    if destination.is_symlink():
        require(destination.resolve() == source, 'Legatura runtime necunoscuta: ' + str(destination))
    elif destination.exists():
        require(destination.is_file(), 'Destinatie runtime neasteptata: ' + str(destination))
    fd, temporary = tempfile.mkstemp(prefix='.install-', dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        shutil.copyfile(source, temporary)
        require(hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(temporary.read_bytes()).digest(),
                'Copia motorului Firebird nu corespunde sursei.')
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    require(not destination.is_symlink(), 'Motorul privat trebuie sa fie un fisier, nu o legatura.')


def prepare_engine(runtime, identity):
    require(not runtime.is_symlink(), 'Director runtime neasteptat.')
    runtime.mkdir(mode=0o750, exist_ok=True)
    engine_files = run(['dpkg', '-L', 'firebird3.0-server-core']).splitlines()
    engines = [Path(p) for p in engine_files if p.endswith('/libEngine12.so')]
    require(len(engines) == 1 and engines[0].is_file(), 'Nu am identificat motorul embedded Engine12.')
    engine = runtime/'plugins/libEngine12.so'
    # Firebird validates the file containing the plugin entry point. A symlink
    # alias can fail this check, despite pointing at the correct library.
    copy_runtime_file(engines[0], engine, runtime)
    common_files = run(['dpkg', '-L', 'firebird3.0-common']).splitlines()
    files = sorted(set(engine_files + common_files))
    for suffix, relative in [('/intl/libfbintl.so', 'intl/libfbintl.so'),
                             ('/intl/fbintl.conf', 'intl/fbintl.conf'),
                             ('/firebird.msg', 'firebird.msg')]:
        candidates = [Path(p) for p in files if p.endswith(suffix) and Path(p).is_file()]
        require(len(candidates) <= 1, 'Mai multe resurse Firebird pentru ' + relative)
        if candidates:
            copy_runtime_file(candidates[0], runtime/relative, runtime)
    owner_tree(runtime, 0, identity.pw_gid)
    # Verify the symbol's owning library under the exact service identity before
    # opening even the synthetic database. Errors include actual/requested paths.
    probe = """import ctypes, json, os, sys
from pathlib import Path
class DlInfo(ctypes.Structure):
    _fields_ = [('dli_fname', ctypes.c_char_p), ('dli_fbase', ctypes.c_void_p),
                ('dli_sname', ctypes.c_char_p), ('dli_saddr', ctypes.c_void_p)]
requested = Path(sys.argv[1]).resolve(strict=True)
plugin = ctypes.CDLL(str(requested))
entry = getattr(plugin, 'firebird_plugin')
libc = ctypes.CDLL(None)
libc.dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(DlInfo)]
libc.dladdr.restype = ctypes.c_int
info = DlInfo()
assert libc.dladdr(ctypes.cast(entry, ctypes.c_void_p), ctypes.byref(info)), 'Nu pot identifica biblioteca pluginului'
actual = os.fsdecode(info.dli_fname)
assert actual == str(requested), 'Engine12: requested=' + str(requested) + '; actual=' + actual
print(json.dumps({'requested': str(requested), 'actual': actual, 'entrypoint': 'firebird_plugin'}))
"""
    result = run(['runuser', '-u', 'gt_financiar', '--', PYTHON, '-I', '-c', probe, engine],
                 cwd=DATA, env=dict(os.environ, FIREBIRD=str(runtime), HOME=str(DATA)))
    print('SAGA_ENGINE12_MODULE_OK: ' + result.strip(), flush=True)


def preflight():
    require(sys.platform.startswith('linux') and os.geteuid()==0,'Ruleaza pe serverul Ubuntu, ca root.')
    require(PYTHON.is_file() and CONF.is_file(),'Instalarea financiara nativa nu a fost gasita.')
    cfg=configparser.RawConfigParser()
    cfg.read(CONF)
    opt=cfg['options']
    require(opt.get('db_name')=='greentech_financiar_test','Baza configurata nu este cea financiara asteptata.')
    require(opt.get('http_port')=='8070' and opt.get('http_interface')=='127.0.0.1','Portul/adresa aplicatiei difera de instalarea verificata.')
    require(Path(opt.get('data_dir','')).resolve()==DATA,'Directorul de date difera de instalarea verificata.')
    require(run(['systemctl','show',SERVICE,'--property=User','--value']).strip()=='gt_financiar','Utilizatorul serviciului nu corespunde.')
    require(run(['systemctl','is-active',SERVICE]).strip()=='active','Serviciul financiar trebuie sa functioneze inainte de actualizare.')
    payload=base64.b64decode(PAYLOAD_B64)
    require(hashlib.sha256(payload).hexdigest()==PAYLOAD_SHA256,'Pachetul incorporat este corupt.')
    plan=run(['apt-get','-s','install','--no-install-recommends','firebird3.0-server-core','libfbclient2'])
    require(not re.search(r'^(Remv |Inst \S+ \[)',plan,re.M),'APT ar elimina sau actualiza pachete existente. Oprire pentru verificarea planului.')
    identity=pwd.getpwnam('gt_financiar')
    require(opt.get('db_user')=='gt_financiar','Rolul bazei difera de instalarea verificata.')
    return opt,payload,identity,plan


def main():
    parser=argparse.ArgumentParser(description='Instaleaza modulul Import SAGA in aplicatia financiara existenta, fara Docker.')
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args()
    print('Pachet: ' + RELEASE, flush=True)
    opt,payload,identity,plan=preflight()
    print('Preflight OK: numai aplicatia financiara, port 8070. Nginx si DNS nu sunt modificate.')
    if not args.install:
        print(plan)
        print('Pentru aplicare: python3 '+Path(__file__).name+' --install')
        return
    os.umask(0o077)
    environment=dict(os.environ,DEBIAN_FRONTEND='noninteractive',NEEDRESTART_MODE='l')
    run(['apt-get','install','-y','--no-install-recommends','firebird3.0-server-core','libfbclient2'],env=environment)
    install_reader_driver()
    runtime=ROOT/'saga-firebird'
    prepare_engine(runtime, identity)
    conf_text='Providers = Engine12\nExternalFileAccess = None\nUdfAccess = None\nDatabaseAccess = Restrict '+str(DATA)+'\nTempDirectories = '+str(DATA/'saga_import_tmp')+'\n'
    private_conf=runtime/'firebird.conf'
    if private_conf.exists():
        require(private_conf.read_text()==conf_text,'Configuratia cititorului exista si difera. Oprire fara suprascriere.')
    else:
        private_conf.write_text(conf_text)
    owner_tree(runtime,0,identity.pw_gid)
    temp_root=DATA/'saga_import_tmp'
    temp_root.mkdir(mode=0o700,exist_ok=True)
    os.chown(temp_root,identity.pw_uid,identity.pw_gid)
    with tempfile.TemporaryDirectory(prefix='saga-stage-',dir=ROOT) as staging_name:
        staging=Path(staging_name)
        with zipfile.ZipFile(io.BytesIO(payload)) as package:
            for entry in package.infolist():
                destination=(staging/entry.filename).resolve()
                require(destination.is_relative_to(staging.resolve()) and not entry.is_dir(),'Cale neasteptata in pachet.')
                require(entry.filename.startswith(MODULE+'/') or entry.filename=='reader-smoke.fdb','Fisier neasteptat in pachet.')
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(package.read(entry))
        owner_tree(staging,0,identity.pw_gid)
        # A real, synthetic Firebird 3 DB verifies Linux reader compatibility
        # before stopping or changing the running Odoo application.
        smoke=Path(tempfile.mkdtemp(prefix='smoke-',dir=temp_root))
        try:
            shutil.copy2(staging/'reader-smoke.fdb',smoke/'source.fdb')
            os.chown(smoke,identity.pw_uid,identity.pw_gid)
            os.chown(smoke/'source.fdb',identity.pw_uid,identity.pw_gid)
            (smoke/'source.fdb').chmod(0o600)
            run(['runuser','-u','gt_financiar','--',PYTHON,'-I',staging/MODULE/'reader/extract_linux.py',smoke/'source.fdb',smoke/'out'],
                env=dict(os.environ,FIREBIRD=str(runtime),PYTHONDONTWRITEBYTECODE='1',HOME=str(DATA)))
            test=json.loads((smoke/'out/SAGA_READER_TEST.jsonl').read_text())
            require(test=={'ID':1,'LABEL':'SAGA reader smoke','AMOUNT':'12.34'},'Cititorul nu a pastrat exact datele testului.')
        finally:
            # Only the exact fresh temporary directory created above is removed.
            require(smoke.parent.resolve()==temp_root.resolve() and smoke.name.startswith('smoke-'),'Director temporar neasteptat.')
            shutil.rmtree(smoke)
        print('SAGA_FIREBIRD_READER_OK')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup=Path('/var/backups/greentech-financiar')/('before-saga-'+stamp)
        backup.mkdir(mode=0o700,parents=True,exist_ok=False)
        pgenv=dict(os.environ,PGPASSWORD=opt['db_password'])
        pgargs=['-h',opt['db_host'],'-p',opt['db_port'],'-U',opt['db_user']]
        installed=run(['psql',*pgargs,'-d',opt['db_name'],'-Atc',"SELECT state FROM ir_module_module WHERE name='greentech_saga_import'"],env=pgenv).strip()=='installed'
        stopped=False
        target=ROOT/'addons'/MODULE
        old=backup/MODULE
        try:
            run(['systemctl','stop',SERVICE])
            stopped=True
            run(['pg_dump',*pgargs,'-Fc','-f',backup/'database.dump',opt['db_name']],env=pgenv)
            run(['pg_restore','--list',backup/'database.dump'])
            shutil.copy2(CONF,backup/'odoo.conf')
            source_filestore=DATA/'filestore'/opt['db_name']
            if source_filestore.is_dir():
                shutil.copytree(source_filestore,backup/'filestore')
            if target.exists():
                require(target.is_dir() and not target.is_symlink(),'Cale addon neasteptata.')
                shutil.copytree(target,old)
            # Files are a complete validated release; only this addon is replaced.
            if target.exists():
                target.rename(backup/'previous-addon')
            shutil.copytree(staging/MODULE,target)
            owner_tree(target,0,identity.pw_gid)
            command=['runuser','-u','gt_financiar','--',PYTHON,ROOT/'source/odoo-bin','-c',CONF,
                '-u' if installed else '-i',MODULE,'--stop-after-init','--no-http']
            result=subprocess.run([str(x) for x in command],capture_output=True,text=True,
                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',HOME=str(DATA),GCOV_PREFIX=str(DATA/'gcov')),timeout=300)
            (backup/'module-update.log').write_text(result.stdout+result.stderr)
            require(result.returncode==0,'Actualizarea modulului a esuat. Vezi '+str(backup/'module-update.log'))
        finally:
            if stopped:
                run(['systemctl','start',SERVICE])
        import time
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8070/web/login',timeout=3) as response:
                    if response.status==200: break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError('Aplicatia nu raspunde dupa actualizare. Backup: '+str(backup))
        action=run(['psql',*pgargs,'-d',opt['db_name'],'-Atc',"SELECT res_id FROM ir_model_data WHERE module='greentech_saga_import' AND name='action_batches'"],env=pgenv).strip()
        require(action.isdigit(),'Actiunea modulului nu a fost gasita.')
        print('SAGA_MODULE_LIVE_OK')
        print('Backup anterior actualizarii: '+str(backup))
        print('Deschide: https://contabilitate.greentechpro.ro/odoo/action-'+action)
        print('Financiar > Import SAGA > Importa backup .fdb. Incarca backupul din browser, apoi Analizeaza si Importa firma.')
        print('Pachetul NU contine datele DARIUSMED si nu a importat nicio firma automat pe server.')


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('OPRIT:',str(exc),file=sys.stderr)
        print('Nu sterge baze sau directoare. Trimite eroarea pentru continuare.',file=sys.stderr)
        raise SystemExit(1)

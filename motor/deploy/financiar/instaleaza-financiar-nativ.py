"""Native Ubuntu installer for the already-uploaded, fixed financial snapshot.

Run as root: python3 /root/instaleaza-financiar-nativ.py --install
Archive: --archive /path/greentech-financiar-server.tar.gz, or automatic discovery
in /root, next to this script, and in the current directory. SHA256 stays mandatory.
No Docker, no Nginx changes, no global Python/Node replacement, no existing DB overwrite.
Without --install, only inspect archive, ports and the planned APT transaction.
Use --resume to validate and finish an interrupted restore, without importing it again.
"""
import argparse
import configparser
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

ROOT = Path('/opt/greentech-financiar')
ARCHIVE = Path('/root/greentech-financiar-server.tar.gz')
ARCHIVE_SHA = 'b1f9ad2863b8ee4717f04d2e8203bb90bd8202b6142ca9ecb206fa56cee57680'
DB = 'greentech_financiar_test'
ROLE = 'gt_financiar'
SERVICE = 'greentech-financiar.service'
CONF_DIR = Path('/etc/greentech-financiar')
CONF = CONF_DIR / 'odoo.conf'
DATA = Path('/var/lib/greentech-financiar')
ACCESS = Path('/root/greentech-financiar-acces.txt')
UNIT = Path('/etc/systemd/system') / SERVICE
STATE = ROOT / '.native-install-state.json'
PYTHON = ROOT / 'venv/bin/python'
PG_BIN = Path('/usr/lib/postgresql/18/bin')
PACKAGES = ['python3-venv', 'build-essential', 'libpq-dev', 'libldap2-dev',
            'libsasl2-dev', 'libssl-dev', 'libffi-dev', 'libxml2-dev', 'libxslt1-dev',
            'libjpeg-dev', 'zlib1g-dev', 'libmagic1t64', 'fontconfig', 'fonts-dejavu-core',
            'postgresql-18', 'postgresql-client-18']
WEBSITES = ['greentechcharity.ro', 'greentechpro.app', 'greentechpro.ro', 'greentechrealestate.ro']


def run(args, *, capture=False, **kw):
    result = subprocess.run([str(x) for x in args], check=True, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, **kw)
    return result.stdout.strip() if capture else ''


def stop(message):
    raise RuntimeError(message)


def port_free(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def locate_archive(explicit=None, search_dirs=None):
    if explicit:
        candidates = [Path(explicit).expanduser().resolve()]
    else:
        directories = search_dirs if search_dirs is not None else [
            Path('/root'), Path(__file__).resolve().parent, Path.cwd()]
        candidates = list(dict.fromkeys((Path(folder) / ARCHIVE.name).resolve() for folder in directories))
    mismatches = []
    for path in candidates:
        if path.is_file():
            actual = sha256(path)
            if actual == ARCHIVE_SHA:
                return path
            mismatches.append(f'{path}: SHA256={actual}')
    if mismatches:
        stop('Arhiva a fost gasita, dar integritatea NU corespunde. Nu continui.\n'
             + '\n'.join(mismatches) + '\nSHA256 asteptat: ' + ARCHIVE_SHA)
    stop('Arhiva nu a fost gasita. Locatii verificate:\n'
         + '\n'.join(str(path) for path in candidates)
         + '\nPuneti arhiva langa script sau indicati calea cu --archive /cale/arhiva.tar.gz.')


def new_file(path, text, mode=0o600):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    path.chmod(mode)


def save_state(state):
    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    STATE.chmod(0o600)


def verify_bundle():
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or sha256(path) != digest:
            stop('Integritate invalida: ' + name)
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    if manifest['database'] != DB or manifest['domain'] != 'contabilitate.greentechpro.ro':
        stop('Alta baza sau alt domeniu in manifest.')
    return manifest


def apt_plan():
    result = run(['apt-get', '--simulate', '--no-install-recommends', '--no-remove',
                  'install', *PACKAGES], capture=True, env=dict(os.environ, LC_ALL='C'))
    # A dependency transaction must not upgrade/remove services or shared libraries already in use.
    changes = apt_existing_changes(result)
    if changes:
        stop('APT ar modifica pachete deja instalate. Nu am executat instalarea.\n' + '\n'.join(changes))
    print(result, flush=True)
    return result


def apt_existing_changes(output):
    return [line for line in output.splitlines()
            if line.startswith('Remv ') or re.match(r'^Inst\s+\S+\s+\[', line)]


def extract_if_needed():
    if ROOT.is_symlink():
        stop('Directorul destinatie este o legatura simbolica.')
    if ROOT.exists():
        if not (ROOT / 'manifest.json').exists():
            stop('Directorul destinatie exista si nu este pachetul financiar verificabil.')
        verify_bundle()
        return
    with tarfile.open(ARCHIVE, 'r:gz') as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if not parts or parts[0] != 'greentech-financiar' or '..' in parts:
                stop('Cale nepermisa in arhiva.')
            if not (member.isfile() or member.isdir()):
                stop('Arhiva contine un tip de fisier nepermis.')
        old = os.umask(0o077)
        try:
            archive.extractall('/opt', filter='data')
        finally:
            os.umask(old)
    ROOT.chmod(0o700)
    verify_bundle()


def preflight(archive_path=None):
    global ARCHIVE
    if sys.platform != 'linux' or os.geteuid() != 0:
        stop('Rulati acest fisier ca root pe serverul Ubuntu, nu pe calculatorul Windows.')
    if not Path('/run/systemd/system').is_dir():
        stop('Este necesar systemd.')
    ARCHIVE = locate_archive(archive_path)
    print('Arhiva verificata: ' + str(ARCHIVE), flush=True)
    if not port_free(8070):
        stop('Portul 8070 este ocupat. Nu am oprit niciun proces.')
    if UNIT.exists() or CONF.exists() or ACCESS.exists() or DATA.exists():
        stop('Exista deja configuratie/date de instalare nativa. Nu se suprascriu; inspectati starea.')
    if STATE.exists():
        state = json.loads(STATE.read_text())
        if state.get('archive_sha') != ARCHIVE_SHA:
            stop('Stare de instalare din alt pachet.')
    else:
        state = {'archive_sha': ARCHIVE_SHA, 'stage': 'preflight', 'postgres_was_absent': True}
        if shutil.which('pg_lsclusters') and run(['pg_lsclusters', '--no-header'], capture=True):
            stop('Am gasit un cluster PostgreSQL existent. Necesita adaptare fara a-l modifica.')
        if not port_free(5432):
            stop('Portul PostgreSQL 5432 este deja folosit.')
        if subprocess.run(['getent', 'passwd', ROLE], stdout=subprocess.DEVNULL).returncode == 0:
            stop('Utilizatorul tehnic exista deja. Nu ii modific permisiunile.')
    run(['nginx', '-t'])
    return state


def websites_snapshot():
    result = {}
    for host in WEBSITES:
        try:
            request = urllib.request.Request('https://' + host, method='HEAD')
            with urllib.request.urlopen(request, timeout=15) as response:
                result[host] = response.status
        except urllib.error.HTTPError as error:
            result[host] = error.code
        except Exception as error:
            result[host] = type(error).__name__
    return result


def python_environment(state):
    bootstrap = ROOT / 'bootstrap'
    if not (bootstrap / 'bin/python').exists():
        run(['python3', '-m', 'venv', bootstrap])
    run([bootstrap / 'bin/python', '-m', 'pip', 'install', 'uv'])
    uv = bootstrap / 'bin/uv'
    environment = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(ROOT/'python'),
        UV_CACHE_DIR=str(ROOT/'.uv-cache'), UV_PYTHON_INSTALL_BIN='false',
        UV_NO_MODIFY_PATH='1', UV_CONCURRENT_BUILDS='1', UV_CONCURRENT_DOWNLOADS='4',
        UV_CONCURRENT_INSTALLS='2', MAKEFLAGS='-j2')
    if not PYTHON.exists():
        run([uv, 'venv', '--python', '3.12', '--managed-python', ROOT/'venv'], env=environment)
    run([PYTHON, '-c', 'import sys; assert sys.version_info[:2] == (3,12); print(sys.version)'])
    run(['nice', '-n', '10', uv, 'pip', 'install', '--python', PYTHON,
         '-r', ROOT/'source/requirements.txt', 'phonenumbers', 'python-slugify'], env=environment)
    freeze = run([uv, 'pip', 'freeze', '--python', PYTHON], capture=True, env=environment)
    (ROOT/'native-python-freeze.txt').write_text(freeze+'\n')
    run([PYTHON, '-c', 'from odoo.release import version; print("Odoo Server", version)'], cwd=ROOT/'source')
    state['stage'] = 'python_ready'
    save_state(state)


def app_config(db_password, master):
    return f'''[options]
admin_passwd = {master}
db_host = 127.0.0.1
db_port = 5432
db_user = {ROLE}
db_password = {db_password}
db_name = {DB}
dbfilter = ^{DB}$
list_db = False
db_maxconn = 32
addons_path = {ROOT}/source/odoo/addons,{ROOT}/addons
data_dir = {DATA}
http_interface = 127.0.0.1
http_port = 8070
proxy_mode = True
workers = 0
max_cron_threads = 0
limit_time_cpu = 120
limit_time_real = 240
limit_memory_soft = 2147483648
limit_memory_hard = 2684354560
log_level = info
smtp_server = 127.0.0.1
smtp_port = 1
'''


def unit_text():
    return f'''[Unit]
Description=GreenTech Financiar DEMO - Odoo 19
After=network.target postgresql@18-main.service
Requires=postgresql@18-main.service

[Service]
Type=simple
User={ROLE}
Group={ROLE}
WorkingDirectory={ROOT}/source
ExecStart={PYTHON} {ROOT}/source/odoo-bin -c {CONF}
Restart=on-failure
RestartSec=5
TimeoutStopSec=60
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=HOME={DATA}
Environment=GCOV_PREFIX={DATA}/gcov
UMask=0077
MemoryMax=3G
CPUQuota=200%
TasksMax=256
Nice=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={DATA}
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
IPAddressDeny=any
IPAddressAllow=localhost

[Install]
WantedBy=multi-user.target
'''


def share_code_readonly(gid):
    os.chown(ROOT, 0, gid)
    ROOT.chmod(0o750)
    # Do not expose backups, bootstrap credentials or the original Docker runtime directory.
    for name in ['source', 'addons', 'python', 'venv']:
        base = ROOT/name
        for directory, dirs, files in os.walk(base, followlinks=False):
            path = Path(directory)
            os.chown(path, 0, gid)
            path.chmod(0o750)
            for filename in files:
                path = Path(directory)/filename
                if not path.is_symlink():
                    executable = bool(path.stat().st_mode & 0o111)
                    os.chown(path, 0, gid)
                    path.chmod(0o750 if executable else 0o640)


def pg_sql(query, db='postgres'):
    return run(['runuser', '-u', 'postgres', '--', PG_BIN/'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                '-h', '/var/run/postgresql', '-p', '5432', '-d', db, '-At'], input=query, capture=True)


def setup_data(state):
    import pwd
    clusters = run(['pg_lsclusters', '--no-header'], capture=True).splitlines()
    if len(clusters) != 1 or not re.match(r'^18\s+main\s+5432\s+', clusters[0]):
        stop('Configuratie PostgreSQL neasteptata: necesita inspectie, fara modificari automate.')
    if not state.get('postgres_was_absent'):
        stop('Nu pot confirma ca acest cluster a fost creat pentru proiect.')
    run(['systemctl', 'start', 'postgresql@18-main.service'])
    if pg_sql('SHOW listen_addresses;') not in ('localhost', '127.0.0.1'):
        stop('PostgreSQL nu este limitat la localhost. Necesita inspectie inainte de restaurare.')
    if pg_sql("SELECT datname FROM pg_database WHERE NOT datistemplate AND datname != 'postgres';"):
        stop('Exista o baza de date in cluster. Nu restaurez peste date existente.')
    if pg_sql(f"SELECT rolname FROM pg_roles WHERE rolname='{ROLE}';"):
        stop('Rolul bazei exista deja. Nu suprascriu o instalare partiala.')
    run(['systemctl', 'set-property', 'postgresql@18-main.service', 'MemoryMax=1G', 'CPUQuota=100%'])
    run(['useradd', '--system', '--user-group', '--home-dir', DATA, '--no-create-home',
         '--shell', '/usr/sbin/nologin', ROLE])
    account = pwd.getpwnam(ROLE)
    share_code_readonly(account.pw_gid)
    CONF_DIR.mkdir(mode=0o750)
    os.chown(CONF_DIR, 0, account.pw_gid)
    DATA.mkdir(mode=0o700)
    os.chown(DATA, account.pw_uid, account.pw_gid)
    db_password, master, login_password = [secrets.token_urlsafe(36) for _ in range(3)]
    new_file(CONF, app_config(db_password, master), 0o640)
    os.chown(CONF, 0, account.pw_gid)
    new_file(ACCESS, 'Adresa: https://contabilitate.greentechpro.ro\nLogin: admin\nParola: ' + login_password + '\n')
    # Names are fixed and the generated password alphabet contains no SQL quoting characters.
    assert re.fullmatch(r'[A-Za-z0-9_-]+', db_password)
    pg_sql(f"CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '{db_password}';\n"
           f"CREATE DATABASE {DB} OWNER {ROLE} TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C.UTF-8' LC_CTYPE 'C.UTF-8';")
    state['stage'] = 'restoring'
    save_state(state)
    with (ROOT/'backup/database.dump').open('rb') as dump:
        # Pass an already-open descriptor; postgres does not need access to private backup directories.
        run(['runuser', '-u', 'postgres', '--', PG_BIN/'pg_restore', '--exit-on-error',
             '--single-transaction', '--no-owner', '--no-privileges', '--role', ROLE,
             '-h', '/var/run/postgresql', '-p', '5432', '-U', 'postgres', '-d', DB], stdin=dump)
    target = DATA/'filestore'/DB
    shutil.copytree(ROOT/'backup/filestore', target)
    for path in [target.parent, target, *target.rglob('*')]:
        os.chown(path, account.pw_uid, account.pw_gid)
        path.chmod(0o700 if path.is_dir() else 0o600)
    finish_restored_data(state, login_password)
    return login_password


def snapshot_verification_code(checks):
    # Normalize representation ONLY. Numeric values stay exact: no rounding or tolerance.
    return f'''
import ast, json
from collections import Counter
from decimal import Decimal
assert env.cr.dbname == {DB!r}
expected = json.loads({json.dumps(checks)!r})
audit = {{}}
failed = []
for label, check in expected.items():
    env.cr.execute(check['sql'])
    raw = env.cr.fetchall()
    types = [column.type_code for column in env.cr.description]
    columns = [column.name for column in env.cr.description]
    actual = [[str(v) if v is not None else None for v in row] for row in raw]
    def canonical(rows):
        result = []
        for row in rows:
            assert len(row) == len(types), 'Column count mismatch: '+label
            values = []
            for value, kind in zip(row, types):
                if value is None:
                    values.append(('null', ''))
                elif kind in (20, 21, 23, 700, 701, 1700):
                    number = Decimal(value)
                    assert number.is_finite(), 'Non-finite value: '+label
                    values.append(('number', number))
                elif kind in (114, 3802):
                    values.append(('json', json.dumps(ast.literal_eval(value), sort_keys=True, ensure_ascii=False)))
                else:
                    values.append(('text', value))
            result.append(tuple(values))
        return Counter(result)
    equal = canonical(actual) == canonical(check['rows'])
    audit[label] = {{'equal':equal,'columns':columns,'expected':check['rows'],'actual':actual,
                    'representation_changed':actual != check['rows']}}
    if not equal:
        failed.append(label)
        print('SNAPSHOT_DIFF', label, json.dumps(audit[label],ensure_ascii=False), flush=True)
    else:
        print('RESTORE MATCH', label,
              '(format/ordine normalizate, valori exacte)' if actual != check['rows'] else '', flush=True)
if failed:
    raise RuntimeError('Diferente reale fata de snapshot: '+', '.join(failed)+'. Nu au fost modificate documente.')
print('SNAPSHOT_ALL_EXACT', flush=True)
'''


def finish_restored_data(state, login_password):
    manifest = json.loads((ROOT/'manifest.json').read_text())
    code = snapshot_verification_code(manifest['checks']) + '''
import uuid, os
env['res.users'].search([('login','=','admin')]).write({'password':os.environ['FINANCE_INITIAL_ADMIN']})
params=env['ir.config_parameter'].sudo()
params.set_param('web.base.url','https://contabilitate.greentechpro.ro')
params.set_param('web.base.url.freeze','True')
params.set_param('report.url','http://127.0.0.1:8070')
params.set_param('database.uuid',str(uuid.uuid4()))
env['ir.cron'].with_context(active_test=False).search([]).write({'active':False})
env['ir.mail_server'].with_context(active_test=False).search([]).write({'active':False})
env['payment.provider'].search([('state','!=','disabled')]).write({'state':'disabled'})
env.cr.commit()
print('NATIVE_RESTORE_OK',flush=True)
'''
    run(['runuser', '-u', ROLE, '--', PYTHON, ROOT/'source/odoo-bin', 'shell', '-c', CONF, '--no-http'],
        input=code, cwd=ROOT/'source', env=dict(os.environ, FINANCE_INITIAL_ADMIN=login_password,
            PYTHONDONTWRITEBYTECODE='1', GCOV_PREFIX=str(DATA/'gcov')))
    state['stage'] = 'restored'
    save_state(state)
    if UNIT.exists():
        if UNIT.read_text() != unit_text():
            stop('Fisierul serviciului exista cu alt continut. Nu il suprascriu.')
    else:
        new_file(UNIT, unit_text(), 0o644)
    run(['systemd-analyze', 'verify', UNIT])
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', '--now', SERVICE])


def resume_install(archive_path=None):
    global ARCHIVE
    if sys.platform != 'linux' or os.geteuid() != 0:
        stop('Reluarea se executa ca root pe serverul Ubuntu.')
    ARCHIVE = locate_archive(archive_path)
    verify_bundle()
    if not STATE.is_file():
        stop('Lipseste starea instalarii initiale.')
    state = json.loads(STATE.read_text())
    if state.get('archive_sha') != ARCHIVE_SHA or state.get('stage') not in ('restoring','restored'):
        stop('Starea instalarii nu permite aceasta reluare: '+str(state.get('stage')))
    if not port_free(8070):
        stop('Portul 8070 este ocupat. Nu opresc serviciul care il utilizeaza.')
    config = configparser.RawConfigParser()
    config.read(CONF)
    needed = {'db_name':DB,'db_host':'127.0.0.1','db_port':'5432','db_user':ROLE,
              'data_dir':str(DATA),'http_port':'8070','http_interface':'127.0.0.1'}
    if any(config.get('options',key,fallback=None) != value for key,value in needed.items()):
        stop('Configuratia nu corespunde instalarii financiare izolate.')
    if pg_sql(f"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='{DB}';") != ROLE:
        stop('Baza restaurata lipseste sau are alt proprietar.')
    # Verify copied attachments, too; never overwrite an existing filestore on resume.
    for source in (ROOT/'backup/filestore').rglob('*'):
        if source.is_file():
            target = DATA/'filestore'/DB/source.relative_to(ROOT/'backup/filestore')
            if not target.is_file() or sha256(target) != sha256(source):
                stop('Atasament lipsa/diferit in copia restaurata: '+str(source.relative_to(ROOT/'backup/filestore')))
    match = re.search(r'^Parola: ([A-Za-z0-9_-]+)$', ACCESS.read_text(), re.MULTILINE)
    if not match:
        stop('Nu pot citi parola generata la instalarea initiala.')
    password = match.group(1)
    before = websites_snapshot()
    if any(not isinstance(status,int) or status >= 500 for status in before.values()):
        stop('Un site existent nu raspunde normal inainte de reluare: '+json.dumps(before))
    print('Verific baza si atasamentele existente. Nu execut pg_restore si nu instalez pachete.', flush=True)
    finish_restored_data(state, password)
    check_http(password)
    run(['nginx','-t'])
    after = websites_snapshot()
    state.update(stage='private_running',websites_after=after)
    save_state(state)
    print('Site-uri inainte:',json.dumps(before))
    print('Site-uri dupa:',json.dumps(after))
    if before != after:
        stop('Raspunsurile site-urilor difera. Verificati comparatia inainte de publicare.')
    print('FINANCIAR_NATIV_OK: http://127.0.0.1:8070 (intern pe server)')
    print('Parola ramane in /root/greentech-financiar-acces.txt. Nginx si DNS nu au fost modificate.')


def check_http(password):
    base = 'http://127.0.0.1:8070'
    session = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    for attempt in range(60):
        try:
            with session.open(base+'/web/login', timeout=5) as response:
                if response.status == 200:
                    break
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(2)
    else:
        stop('Serviciul nu raspunde. Consultati journalctl -u greentech-financiar -n 100 --no-pager.')

    def rpc(path, params):
        request = urllib.request.Request(base+path, json.dumps({'jsonrpc':'2.0','method':'call','id':1,'params':params}).encode(),
                                         {'Content-Type':'application/json'})
        with session.open(request, timeout=120) as response:
            result = json.load(response)
        if 'error' in result:
            stop('Eroare Odoo: '+str(result['error'].get('data',{}).get('message',result['error'].get('message'))))
        return result['result']

    def call(model, method, args, kw=None):
        kwargs={'context':{'lang':'ro_RO','tz':'Europe/Bucharest'}, **(kw or {})}
        return rpc('/web/dataset/call_kw/'+model+'/'+method, {'model':model,'method':method,'args':args,'kwargs':kwargs})

    if not rpc('/web/session/authenticate', {'db':DB,'login':'admin','password':password}).get('uid'):
        stop('Autentificarea a esuat.')
    reports=call('mis.report.instance','search_read',[[]],{'fields':['name']})
    for report in reports:
        data=call('mis.report.instance','compute',[[report['id']]])
        if any(str(cell.get('val_r','')).startswith('#') for row in data['body'] for cell in row['cells']):
            stop('Formula invalida in raport: '+str(report['name']))
    for model in ['gt.payroll.slip','gt.payroll.period','gt.payroll.trip']:
        views=call(model,'get_views',[],{'views':[[False,'list'],[False,'form']]})
        if not views['views']['form']['arch']:
            stop('Formular lipsa: '+model)
    with session.open(base+'/odoo',timeout=60) as response:
        page=response.read().decode()
    assets=re.findall(r'<script[^>]+src=[\"\'](/web/assets/[^\"\']+)',page)
    if not assets:
        stop('Pagina Odoo nu contine bundle-urile JavaScript asteptate.')
    for asset in assets:
        with session.open(base+asset,timeout=120) as response:
            if response.status != 200 or len(response.read()) < 100:
                stop('Asset invalid: '+asset)
    print('NATIVE_HTTP_OK: login, rapoarte DEMO, formulare HR, interfata si assets.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--install',action='store_true')
    modes.add_argument('--resume',action='store_true',help='Verifica si finalizeaza baza deja restaurata, fara reimport.')
    parser.add_argument('--archive',help='Calea arhivei; implicit cauta in /root, langa script si in directorul curent.')
    args=parser.parse_args()
    if args.resume:
        resume_install(args.archive)
        return
    state=preflight(args.archive)
    plan=apt_plan()
    if not args.install:
        print('Verificari preliminare OK. Pentru instalare utilizati --install.')
        return
    baseline=websites_snapshot()
    if any(not isinstance(status,int) or status >= 500 for status in baseline.values()):
        stop('Un site existent nu trece verificarea initiala: '+json.dumps(baseline))
    extract_if_needed()
    state['websites_before']=baseline
    save_state(state)
    (ROOT/'native-apt-plan.txt').write_text(plan+'\n')
    # No global upgrade/removal. needrestart lists services instead of restarting existing sites.
    run(['apt-get','-y','--no-install-recommends','--no-remove','install',*PACKAGES],
        env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',NEEDRESTART_MODE='l'))
    state['stage']='packages_ready'
    save_state(state)
    python_environment(state)
    password=setup_data(state)
    check_http(password)
    run(['nginx','-t'])
    after=websites_snapshot()
    state.update(stage='private_running',websites_after=after)
    save_state(state)
    print('Site-uri inainte:',json.dumps(baseline))
    print('Site-uri dupa:',json.dumps(after))
    if after != baseline:
        stop('Raspunsurile site-urilor difera; verificati comparatia de mai sus inainte de publicare.')
    print('FINANCIAR_NATIV_OK: http://127.0.0.1:8070 (intern pe server)')
    print('Date acces salvate privat in /root/greentech-financiar-acces.txt; parola nu este afisata in log.')
    print('Domeniul HTTPS nu este activat inca. Nginx si DNS nu au fost modificate.')
    print('PDF wkhtmltopdf nu a fost instalat in acest pas; HTML/Excel raman disponibile.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        if isinstance(error,subprocess.CalledProcessError):
            print('EROARE: comanda a esuat, cod',error.returncode,file=sys.stderr)
            if error.stderr:
                # SQL passed by stdin and secrets passed by environment are never printed.
                print(error.stderr,file=sys.stderr)
        else:
            print('OPRIT:',error,file=sys.stderr)
        print('Nu stergeti baze sau directoare. Trimiteti ultima eroare pentru continuare.',file=sys.stderr)
        sys.exit(1)

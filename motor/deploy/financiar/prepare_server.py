"""Generate NEW credentials locally on the server; never install or reload anything."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import sys

ROOT = Path(__file__).resolve().parent
DOMAIN = 'contabilitate.greentechpro.ro'


def main():
    if sys.platform != 'linux' or ROOT != Path('/opt/greentech-financiar'):
        raise SystemExit('Ruleaza numai din /opt/greentech-financiar pe Linux.')
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit('Integritate invalida: ' + name)
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    assert manifest['database'] == 'greentech_financiar_test'
    assert manifest['domain'] == DOMAIN
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', 8070))
        except OSError:
            raise SystemExit('Portul 8070 este ocupat. Nu a fost oprit niciun serviciu.')
    runtime = ROOT / 'runtime'
    if runtime.exists():
        raise SystemExit('runtime exista deja. Parolele si configuratia nu vor fi suprascrise.')
    os.umask(0o077)
    runtime.mkdir(mode=0o700)
    db_admin, db_odoo, master, admin = [secrets.token_urlsafe(36) for _ in range(4)]
    files = {
        'db-admin-password': db_admin,
        'admin-password': admin,
        'odoo.conf': f'''[options]
admin_passwd = {master}
db_host = db
db_port = 5432
db_user = finance_odoo
db_password = {db_odoo}
db_name = greentech_financiar_test
dbfilter = ^greentech_financiar_test$
list_db = False
db_maxconn = 32
addons_path = /opt/finance-source/odoo/addons,/opt/finance-addons
data_dir = /var/lib/odoo
http_interface = 0.0.0.0
http_port = 8069
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
''',
    }
    for name, value in files.items():
        path = runtime / name
        path.write_text(value + '\n', encoding='utf-8')
        # Parent dir 0700 protects credentials on the host. Container Odoo reads only its config.
        path.chmod(0o444)
    print('Integritate OK. Configuratie si parole NOI create in runtime/ (director privat).')
    print('Nicio instalare, nicio modificare Nginx, niciun serviciu pornit.')


if __name__ == '__main__':
    main()

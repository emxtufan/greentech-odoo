"""One-time restore ONLY into the new isolated PostgreSQL container, then compare totals."""
import configparser
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile

import psycopg2
from psycopg2 import sql

DB = 'greentech_financiar_test'
manifest = json.loads(Path('/manifest.json').read_text())
assert manifest['database'] == DB
config = configparser.RawConfigParser()
config.read('/run/finance/odoo.conf')
options = config['options']
assert options['db_host'] == 'db' and options['db_name'] == DB
admin_password = Path('/run/finance/db-admin-password').read_text().strip()
admin = dict(host='db', port=5432, user='postgres', password=admin_password)
connection = psycopg2.connect(dbname='postgres', **admin)
connection.autocommit = True
with connection.cursor() as cur:
    cur.execute('SELECT datname FROM pg_database WHERE NOT datistemplate AND datname != %s', ('postgres',))
    if cur.fetchall():
        raise SystemExit('Exista deja o baza in acest container. Restaurarea nu suprascrie date.')
    cur.execute('SELECT rolname FROM pg_roles WHERE rolname = %s', (options['db_user'],))
    if cur.fetchone():
        raise SystemExit('Rolul aplicatiei exista deja; verificati o eventuala restaurare intrerupta.')
    cur.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s').format(
        sql.Identifier(options['db_user'])), (options['db_password'],))
    cur.execute(sql.SQL('CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING %s LC_COLLATE %s LC_CTYPE %s').format(
        sql.Identifier(DB), sql.Identifier(options['db_user'])), ('UTF8', 'C.UTF-8', 'C.UTF-8'))
connection.close()
environment = dict(os.environ, PGPASSWORD=admin_password)
subprocess.run(['pg_restore', '--exit-on-error', '--single-transaction', '--no-owner', '--no-privileges',
                '--role', options['db_user'], '-h', 'db', '-U', 'postgres', '-d', DB,
                '/backup/database.dump'], env=environment, check=True)

with psycopg2.connect(dbname=DB, **admin) as connection:
    with connection.cursor() as cur:
        for label, expected in manifest['checks'].items():
            cur.execute(expected['sql'])
            actual = [[str(v) if v is not None else None for v in row] for row in cur.fetchall()]
            if actual != expected['rows']:
                raise RuntimeError(f'Datele restaurate difera: {label}')
            print('PASS', label, flush=True)

target = Path('/var/lib/odoo/filestore') / DB
if target.exists():
    raise SystemExit('Filestore destinatie exista deja; nu se suprascrie.')
shutil.copytree('/backup/filestore', target)
owner = pwd.getpwnam('odoo')
for path in [Path('/var/lib/odoo'), target.parent, target, *target.rglob('*')]:
    os.chown(path, owner.pw_uid, owner.pw_gid)
    path.chmod(0o700 if path.is_dir() else 0o600)

# ONLY the restored copy: new login secret, new database UUID, no outgoing integrations.
new_password = Path('/run/finance/admin-password').read_text().strip()
shell_code = '''
import os, uuid
assert env.cr.dbname == 'greentech_financiar_test'
env['res.users'].search([('login','=','admin')]).write({'password': os.environ['FINANCE_NEW_ADMIN']})
params = env['ir.config_parameter'].sudo()
params.set_param('web.base.url', 'https://contabilitate.greentechpro.ro')
params.set_param('web.base.url.freeze', 'True')
params.set_param('database.uuid', str(uuid.uuid4()))
params.set_param('report.url', 'http://127.0.0.1:8069')
env['ir.cron'].with_context(active_test=False).search([]).write({'active': False})
env['ir.mail_server'].with_context(active_test=False).search([]).write({'active': False})
env['payment.provider'].search([('state','!=','disabled')]).write({'state': 'disabled'})
env.cr.commit()
print('RESTORE_OK: copia financiara, parola noua, automatizari dezactivate')
'''
with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as tmp:
    tmp.write(Path('/run/finance/odoo.conf').read_text())
    temporary_config = Path(tmp.name)
os.chown(temporary_config, owner.pw_uid, owner.pw_gid)
try:
    subprocess.run(['/opt/finance-venv/bin/python', '/opt/finance-source/odoo-bin', 'shell',
                    '-c', str(temporary_config), '--no-http'], input=shell_code, text=True,
                   user=owner.pw_uid, group=owner.pw_gid,
                   env=dict(os.environ, FINANCE_NEW_ADMIN=new_password), check=True)
finally:
    temporary_config.unlink()
print('Restaurare finalizata. Porniti serviciul odoo separat; nu a fost modificat Nginx.')

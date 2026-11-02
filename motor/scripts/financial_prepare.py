"""Create an isolated financial sandbox. Existing Odoo databases are not edited."""
import ast
import configparser
import json
from pathlib import Path
import secrets
import sys
import requests

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
DB = 'greentech_financiar_test'
cfg = configparser.RawConfigParser()
cfg.read(ROOT / 'config/odoo.conf', encoding='utf-8-sig')
opts = cfg['options']
package = json.loads((ROOT / 'logs/financial-package-sources.json').read_text(encoding='utf-8'))
paths = [ROOT / 'odoo/odoo/addons', ROOT / 'odoo/addons', ROOT.parent / 'module']
modules = ['l10n_ro', 'contacts']
for source in package['provenance']:
    paths.append(ROOT / 'third_party_addons' / source['repo'].split('/')[1])
    modules.extend(source['modules'])
opts.update(addons_path=','.join(str(p) for p in paths), http_port='8070',
    http_interface='127.0.0.1', db_name=DB, dbfilter='^' + DB + '$',
    max_cron_threads='0', list_db='False', workers='0',
    logfile=str(ROOT / 'logs/odoo-financiar.log'))
opts['data_dir'] = str(ROOT / 'data-runtime')
with (ROOT / 'config/odoo-financiar.conf').open('w', encoding='utf-8') as out:
    cfg.write(out)
(ROOT / 'logs/financial-modules.json').write_text(json.dumps(modules), encoding='utf-8')
available = {p.name for path in paths if path.exists() for p in path.iterdir() if p.is_dir() and (p/'__manifest__.py').exists()}
for path in paths[3:]:
    for manifest in path.glob('*/__manifest__.py'):
        spec = ast.literal_eval(manifest.read_text(encoding='utf-8'))
        missing = set(spec.get('depends', [])) - available
        if missing:
            raise RuntimeError(f'{manifest.parent.name}: missing {missing}')
credentials_path = ROOT / 'config/acces-financiar-test.json'
if credentials_path.exists():
    credentials = json.loads(credentials_path.read_text())
else:
    credentials = {'database': DB, 'login': 'admin', 'password': secrets.token_urlsafe(22),
                   'url': 'http://127.0.0.1:8070/odoo?db=' + DB}
    credentials_path.write_text(json.dumps(credentials, indent=2), encoding='utf-8')
session = requests.Session()
listed = session.post('http://127.0.0.1:8069/web/database/list', json={
    'jsonrpc': '2.0', 'method': 'call', 'params': {}, 'id': 1}, timeout=15).json()
if DB not in listed.get('result', []):
    print('Creating separate Romanian financial database...', flush=True)
    response = session.post('http://127.0.0.1:8069/web/database/create', data={
        'master_pwd': opts['admin_passwd'], 'name': DB, 'lang': 'ro_RO',
        'login': credentials['login'], 'password': credentials['password'],
        'country_code': 'ro', 'phone': ''}, timeout=360)
    response.raise_for_status()
    if 'Database creation error' in response.text:
        raise RuntimeError('Database creation failed; inspect local Odoo log.')
print('Configuration prepared; credentials saved locally without displaying them.')

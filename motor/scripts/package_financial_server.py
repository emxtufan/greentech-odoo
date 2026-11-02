"""Package an exact consistent snapshot of ONLY the financial demo, without changing it."""
import ast
import configparser
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
DB = 'greentech_financiar_test'
config = configparser.RawConfigParser()
config.read(ROOT / 'config/odoo-financiar.conf', encoding='utf-8')
options = config['options']
assert options['db_name'] == DB
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
out = ROOT / 'logs/server-transfer' / stamp
package = out / 'greentech-financiar'
package.mkdir(parents=True)
for source in (ROOT / 'deploy/financiar').iterdir():
    if source.is_file():
        shutil.copy2(source, package / source.name)

def tree(source, target):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git', '.pytest_cache'))

connection = psycopg2.connect(host=options['db_host'], port=options['db_port'],
    user=options['db_user'], password=options['db_password'], dbname=DB)
connection.set_session(isolation_level='REPEATABLE READ', readonly=True)
manifest = {'database': DB, 'domain': 'contabilitate.greentechpro.ro',
            'created_utc': datetime.now(timezone.utc).isoformat(), 'checks': {}, 'modules': []}
queries = {
    'installed_modules': "SELECT name, latest_version FROM ir_module_module WHERE state='installed' ORDER BY name",
    'journal_entries': "SELECT move_type, state, count(*), coalesce(sum(amount_total),0) FROM account_move GROUP BY move_type,state ORDER BY move_type,state",
    'ledger': 'SELECT count(*), sum(debit), sum(credit), sum(balance) FROM account_move_line',
    'payroll': 'SELECT s.id, s.employee_id, p.date_from, p.date_to, s.state, s.net_pay, s.move_id, s.payment_move_id FROM gt_payroll_slip s JOIN gt_payroll_period p ON p.id=s.period_id ORDER BY s.id',
    'trips': 'SELECT id, employee_id, state, total_amount, taxable_amount FROM gt_payroll_trip ORDER BY id',
    'reports': 'SELECT id, name FROM mis_report_instance ORDER BY id',
    'attachments': 'SELECT count(*) FROM ir_attachment',
    'employees': 'SELECT id, name, gt_payroll_demo FROM hr_employee ORDER BY id',
}
with connection.cursor() as cursor:
    cursor.execute('SELECT pg_export_snapshot()')
    snapshot = cursor.fetchone()[0]
    for name, query in queries.items():
        cursor.execute(query)
        manifest['checks'][name] = {'sql': query,
            'rows': [[str(v) if v is not None else None for v in row] for row in cursor.fetchall()]}
    modules = [row[0] for row in manifest['checks']['installed_modules']['rows']]
    paths = [Path(p.strip()) for p in options['addons_path'].split(',')]
    mapping = {}
    for module in modules:
        matches = [p / module for p in paths if (p / module / '__manifest__.py').exists()]
        if len(matches) != 1:
            raise RuntimeError(f'Module missing/ambiguous: {module}: {matches}')
        mapping[module] = matches[0]
        metadata = ast.literal_eval((matches[0] / '__manifest__.py').read_text(encoding='utf-8'))
        missing = set(metadata.get('depends', [])) - set(modules)
        if missing:
            raise RuntimeError(f'Missing dependencies for {module}: {missing}')
        manifest['modules'].append({'name': module, 'source': matches[0].relative_to(ROOT).as_posix()})
    assert not {'construction_erp', 'greentech_demo'}.intersection(mapping)
    cursor.execute('SELECT store_fname, checksum FROM ir_attachment WHERE store_fname IS NOT NULL ORDER BY id')
    attachments = cursor.fetchall()
    backup = package / 'backup'
    backup.mkdir()
    pg = Path(r'C:\Program Files\PostgreSQL\18\bin')
    subprocess.run([str(pg / 'pg_dump.exe'), '-h', options['db_host'], '-p', options['db_port'],
                    '-U', options['db_user'], '-Fc', '--snapshot', snapshot,
                    '-f', str(backup / 'database.dump'), DB],
                   env=dict(os.environ, PGPASSWORD=options['db_password']), check=True, capture_output=True)
    subprocess.run([str(pg / 'pg_restore.exe'), '--list', str(backup / 'database.dump')],
                   check=True, capture_output=True)
    store = Path(options['data_dir']) / 'filestore' / DB
    copied = set()
    for name, checksum in attachments:
        if name in copied:
            continue
        if not re.fullmatch(r'[a-f0-9]{2}/[a-f0-9]{40}', name):
            raise RuntimeError('Unexpected attachment path')
        source = store / name
        content = source.read_bytes()
        if checksum and hashlib.sha1(content).hexdigest() != checksum:
            raise RuntimeError('Attachment checksum mismatch: ' + name)
        target = backup / 'filestore' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        copied.add(name)
connection.rollback()
connection.close()
print('Snapshot DB + filestore verified:', len(copied), 'files', flush=True)

# Core from the current checkout; installed addons only, preserving actual local patches.
core = package / 'source'
core.mkdir()
tree(ROOT / 'odoo/odoo', core / 'odoo')
for name in ['odoo-bin', 'requirements.txt', 'LICENSE', 'COPYRIGHT', 'setup.cfg', 'setup.py', 'README.md']:
    shutil.copy2(ROOT / 'odoo' / name, core / name)
addons = package / 'addons'
addons.mkdir()
for module, source in mapping.items():
    if module != 'base':
        tree(source, addons / module)
manifest['attachment_files'] = len(copied)
(package / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
files = sorted(p for p in package.rglob('*') if p.is_file())
sums = [hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.relative_to(package).as_posix() for p in files]
(package / 'SHA256SUMS').write_text('\n'.join(sums) + '\n', encoding='utf-8')
archive = out / 'greentech-financiar-server.tar.gz'
with tarfile.open(archive, 'w:gz', compresslevel=6) as tar:
    tar.add(package, arcname='greentech-financiar', recursive=False)
    for path in [*files, package / 'SHA256SUMS']:
        tar.add(path, arcname='greentech-financiar/' + path.relative_to(package).as_posix(), recursive=False)
with tarfile.open(archive, 'r:gz') as tar:
    members = {m.name: m for m in tar.getmembers() if m.isfile()}
    for entry in sums:
        digest, name = entry.split('  ', 1)
        if hashlib.sha256(tar.extractfile(members['greentech-financiar/' + name]).read()).hexdigest() != digest:
            raise RuntimeError('Archive checksum mismatch: ' + name)
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_name(archive.name + '.sha256').write_text(digest + '  ' + archive.name + '\n', encoding='utf-8')
result = {'archive': str(archive), 'directory': str(package), 'bytes': archive.stat().st_size,
          'sha256': digest, 'modules': len(modules), 'attachment_files': len(copied), 'files': len(files)}
(ROOT / 'logs/financial-server-package.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2), flush=True)

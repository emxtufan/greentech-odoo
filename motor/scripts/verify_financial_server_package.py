"""Test a real restoration into a temporary local DB; never replace any user DB."""
import configparser
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
package = Path(sys.argv[1]).resolve()
assert package.is_relative_to(ROOT / 'logs/server-transfer')
manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
assert manifest['database'] == 'greentech_financiar_test'
config = configparser.RawConfigParser()
config.read(ROOT / 'config/odoo-financiar.conf', encoding='utf-8')
options = config['options']
credentials = dict(host=options['db_host'], port=options['db_port'], user=options['db_user'], password=options['db_password'])
name = 'gt_transfer_check_' + datetime.now().strftime('%Y%m%d_%H%M%S')
created = False
connection = psycopg2.connect(dbname='postgres', **credentials)
connection.autocommit = True
checks = []
try:
    with connection.cursor() as cur:
        cur.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        created = True
    restored = subprocess.run([r'C:\Program Files\PostgreSQL\18\bin\pg_restore.exe',
        '--exit-on-error', '--single-transaction', '--no-owner', '--no-privileges',
        '-h', options['db_host'], '-p', options['db_port'], '-U', options['db_user'],
        '-d', name, str(package / 'backup/database.dump')],
        env=dict(os.environ, PGPASSWORD=options['db_password']), capture_output=True, text=True)
    if restored.returncode:
        raise RuntimeError(restored.stderr)
    with psycopg2.connect(dbname=name, **credentials) as test:
        with test.cursor() as cur:
            for label, expected in manifest['checks'].items():
                cur.execute(expected['sql'])
                actual = [[str(v) if v is not None else None for v in row] for row in cur.fetchall()]
                assert actual == expected['rows'], label
                checks.append(label)
                print('RESTORE MATCH', label, flush=True)
    test.close()

    # Load the bundled source and only the bundled addons. No server is opened.
    test_config = package.parent / 'restore-check.conf'
    test_data = package.parent / 'restore-check-data'
    test_data.mkdir(exist_ok=True)
    config['options'].update(db_name=name, dbfilter='^' + name + '$',
        addons_path=','.join(str(p) for p in [package/'source/odoo/addons', package/'addons']),
        data_dir=str(test_data), logfile=str(package.parent/'restore-check.log'),
        max_cron_threads='0')
    with test_config.open('w', encoding='utf-8') as stream:
        config.write(stream)
    code = """
assert len(env['ir.module.module'].search([('state','=','installed')])) == 91
assert len(env['gt.payroll.slip'].search([])) == 6
assert env['ir.mail_server']._fields.get('active')
for model in ['gt.payroll.slip','gt.payroll.period','gt.payroll.trip']:
    result=env[model].get_views([(False,'list'),(False,'form')])
    assert result['views']['form']['arch']
env.cr.rollback()
print('BUNDLED_REGISTRY_OK')
"""
    try:
        result = subprocess.run([str(ROOT/'.venv/Scripts/python.exe'), str(package/'source/odoo-bin'),
            'shell', '-c', str(test_config), '--no-http'], input=code, text=True,
            capture_output=True, timeout=180, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        (package.parent/'restore-check-output.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
        assert result.returncode == 0 and 'BUNDLED_REGISTRY_OK' in result.stdout, 'Bundled registry failed: inspect restore-check-output.txt/log'
        checks.append('bundled_source_registry_and_hr_views')
        print('BUNDLED_REGISTRY_OK', flush=True)
    finally:
        test_config.unlink(missing_ok=True)
finally:
    if created:
        with connection.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
    connection.close()

report = {'checks': checks, 'passed': len(checks), 'temporary_database_removed': True,
          'scope': 'Local PostgreSQL 18 + bundled Odoo source; Docker/Linux/remote HTTPS not tested'}
(package.parent/'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report), flush=True)

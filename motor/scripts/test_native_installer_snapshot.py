"""Regression checks for exact cross-platform restore comparison and no-reimport recovery."""
import configparser
from contextlib import redirect_stdout
from decimal import Decimal
import importlib.util
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT/'deploy/financiar/instaleaza-financiar-nativ.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
passed = []


class Cursor:
    dbname = 'greentech_financiar_test'

    def __init__(self, rows, types):
        self.rows = rows
        self.description = [SimpleNamespace(type_code=t, name='column_'+str(i)) for i,t in enumerate(types)]

    def execute(self, query):
        assert query.startswith('SELECT')

    def fetchall(self):
        return self.rows


def case(name, expected, actual, types, matches):
    cursor = Cursor(actual, types)
    env = SimpleNamespace(cr=cursor)
    code = installer.snapshot_verification_code({'test':{'sql':'SELECT test','rows':expected}})
    output = StringIO()
    try:
        with redirect_stdout(output):
            exec(compile(code, '<snapshot-test>', 'exec'), {'env':env})
    except RuntimeError as error:
        assert not matches, (name, error)
        assert 'SNAPSHOT_DIFF' in output.getvalue()
    else:
        assert matches, name
        assert 'SNAPSHOT_ALL_EXACT' in output.getvalue()
    passed.append(name)


case('numeric_scale_only', [['entry','53','338986.50']],
     [('entry',53,Decimal('338986.5000'))], [1043,20,1700], True)
case('row_order_only', [['draft','1'],['posted','53']],
     [('posted',53),('draft',1)], [1043,20], True)
case('one_cent_rejected', [['entry','53','338986.50']],
     [('entry',53,Decimal('338986.51'))], [1043,20,1700], False)
case('tiny_numeric_change_rejected_without_tolerance', [['1.00000000']],
     [(Decimal('1.00000001'),)], [1700], False)
case('changed_count_rejected', [['53']], [(54,)], [20], False)
case('duplicate_row_rejected', [['1']], [(1,),(1,)], [20], False)
case('null_not_zero', [[None]], [(0,)], [1700], False)
case('json_order_only', [["{'ro_RO': 'Raport', 'en_US': 'Report'}"]],
     [({'en_US':'Report','ro_RO':'Raport'},)], [3802], True)

# Capture the actual finalization program. No subprocess, filesystem mutation or service runs.
package = Path(json.loads((ROOT/'logs/financial-server-package.json').read_text())['directory'])
captured = []
with patch.object(installer,'ROOT',package), patch.object(installer,'save_state'), \
     patch.object(installer,'new_file'), patch.object(installer,'UNIT',ROOT/'logs/not-created-native-unit.service'), \
     patch.object(installer,'run',side_effect=lambda args,**kw:captured.append((args,kw)) or ''):
    installer.finish_restored_data({'stage':'restoring'}, 'test-password-only')
program = next(kw['input'] for args,kw in captured if 'input' in kw)
assert all('pg_restore' not in ' '.join(map(str,args)) for args,kw in captured)
passed.append('finalization_does_not_reimport')


class ReadonlyCursor:
    dbname = 'greentech_financiar_test'

    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query):
        assert query.startswith('SELECT')
        self.cursor.execute(query)

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def description(self):
        return self.cursor.description

    def commit(self):
        pass  # Read-only database; ORM changes below are simulated in memory only.


class FakeModel:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    def search(self, *args): return self
    def sudo(self): return self
    def with_context(self, **kw): return self

    def write(self, values):
        assert isinstance(values, dict)
        self.calls.append((self.name,values))

    def set_param(self, key, value):
        self.calls.append((key,value))


class FakeEnv:
    def __init__(self, cursor):
        self.cr, self.calls = cursor, []

    def __getitem__(self, name):
        return FakeModel(name,self.calls)


cfg=configparser.RawConfigParser()
cfg.read(ROOT/'config/odoo-financiar.conf',encoding='utf-8')
o=cfg['options']
connection=psycopg2.connect(host=o['db_host'],port=o['db_port'],user=o['db_user'],
                           password=o['db_password'],dbname=o['db_name'])
connection.set_session(readonly=True)
try:
    with connection.cursor() as cursor:
        fake=FakeEnv(ReadonlyCursor(cursor))
        with patch.dict('os.environ',{'FINANCE_INITIAL_ADMIN':'test-password-only'}):
            exec(compile(program,'<actual-finalizer>','exec'),{'env':fake})
        assert ('res.users',{'password':'test-password-only'}) in fake.calls
        passed.append('all_snapshot_queries_match_live_readonly_database')
        passed.append('generated_finalizer_runs_with_simulated_orm_writes')
finally:
    connection.rollback()
    connection.close()

report={'passed':len(passed),'checks':passed,
        'limits':'Server discrepancy still needs remote evidence; Linux services were not run.'}
(ROOT/'logs/native-snapshot-comparison-tests.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))

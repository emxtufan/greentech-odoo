"""Isolated Firebird 3 reader. Requires fdb==2.0.4 and an embedded engine12."""
import base64
import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sys


def encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {'base64': base64.b64encode(value).decode('ascii')}
    raise TypeError(type(value).__name__)


def load_driver():
    import fdb
    if not callable(getattr(fdb, 'connect', None)):
        raise RuntimeError(
            'Cititorul fdb nu este incarcat corect pentru utilizatorul serviciului. '
            'Reinstaleaza pachetul cu instalatorul actualizat si verifica permisiunile. '
            'Fisier=' + repr(getattr(fdb, '__file__', None)) +
            '; directoare=' + repr(list(getattr(fdb, '__path__', []))))
    return fdb


def main():
    private_runtime = Path('/opt/greentech-financiar/saga-firebird')
    if private_runtime.is_dir() and 'FIREBIRD' not in os.environ:
        os.environ['FIREBIRD'] = str(private_runtime)
    if private_runtime.is_dir():
        os.environ.setdefault('FIREBIRD_LOCK','/var/lib/greentech-financiar/saga_import_tmp')
        os.environ.setdefault('FIREBIRD_TMP','/var/lib/greentech-financiar/saga_import_tmp')
    fdb = load_driver()
    database, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    library = os.environ.get('SAGA_FIREBIRD_LIBRARY')
    connection = fdb.connect(database=str(database), user='SYSDBA', charset='UTF8',
                             fb_library_name=library, no_gc=True, no_db_triggers=True, no_linger=True, utf8params=True)
    try:
        connection.begin(tpb=(fdb.isc_tpb_version3, fdb.isc_tpb_read, fdb.isc_tpb_concurrency, fdb.isc_tpb_wait))
        cursor = connection.cursor()
        cursor.execute('SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 AND RDB$VIEW_BLR IS NULL ORDER BY RDB$RELATION_NAME')
        names = [row[0] for row in cursor.fetchall()]
        counts = {}
        target.mkdir(parents=True, exist_ok=True)
        for name in names:
            if not re.fullmatch(r'[A-Z0-9_]+',name):
                raise ValueError('Unsupported table identifier')
            cursor.execute('SELECT * FROM "' + name + '"')
            columns = [x[0] for x in cursor.description]
            count = 0
            with (target/(name+'.jsonl')).open('w',encoding='utf-8') as stream:
                for row in cursor:
                    stream.write(json.dumps(dict(zip(columns,row)),ensure_ascii=False,default=encode)+'\n')
                    count += 1
            cursor.execute('SELECT COUNT(*) FROM "' + name + '"')
            assert cursor.fetchone()[0] == count
            counts[name] = count
        (target/'counts.json').write_text(json.dumps(counts),encoding='utf-8')
        connection.rollback()
    finally:
        connection.close()


if __name__ == '__main__':
    main()

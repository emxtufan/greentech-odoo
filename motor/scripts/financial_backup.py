"""Back up the financial database and filestore, including imported company data."""
import configparser
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
config = configparser.RawConfigParser()
config.read(ROOT / 'config/odoo-financiar.conf',encoding='utf-8')
opt = config['options']
assert opt['db_name'] == 'greentech_financiar_test'
pg_dump = Path(r'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe')
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
folder = ROOT / 'logs/backups'
folder.mkdir(exist_ok=True)
dump = folder / ('financiar-' + stamp + '.dump')
environment = dict(os.environ, PGPASSWORD=opt['db_password'])
subprocess.run([str(pg_dump),'-h',opt['db_host'],'-p',opt['db_port'],'-U',opt['db_user'],
    '-Fc','-f',str(dump),opt['db_name']],env=environment,check=True,capture_output=True)
subprocess.run([str(pg_dump.with_name('pg_restore.exe')),'--list',str(dump)],check=True,capture_output=True)
target = folder / ('greentech-financiar-test-' + stamp + '.zip')
filestore = Path(opt['data_dir']) / 'filestore' / opt['db_name']
with ZipFile(target,'w',ZIP_DEFLATED) as z:
    z.write(dump,'database.dump')
    if filestore.exists():
        for path in filestore.rglob('*'):
            if path.is_file():
                z.write(path,'filestore/' + path.relative_to(filestore).as_posix())
    z.writestr('README.txt','PostgreSQL 18 custom-format dump + Odoo 19 filestore. Contains imported company accounting data as well as demo data.\nCredentials are excluded. Restore into a NEW database; do not overwrite EMI.\n')
with ZipFile(target) as z:
    assert z.testzip() is None
(ROOT/'logs/financial-backup.json').write_text(json.dumps({'path':str(target),'bytes':target.stat().st_size},indent=2),encoding='utf-8')
print('Verified backup:',target.name,target.stat().st_size,'bytes')

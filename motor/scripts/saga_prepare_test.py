"""Create a uniquely named local copy for testing the SAGA upload/import module."""
import configparser
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'logs/saga-migration'
cfg = configparser.RawConfigParser()
cfg.read(ROOT/'config/odoo-financiar.conf',encoding='utf-8')
opt = cfg['options']
assert opt['db_name']=='greentech_financiar_test'
db = 'gt_saga_verify_'+datetime.now().strftime('%Y%m%d_%H%M%S')
pg = Path(r'C:\Program Files\PostgreSQL\18\bin')
dump = BASE/'before-saga.dump'
connection_args = ['-h',opt['db_host'],'-p',opt['db_port'],'-U',opt['db_user']]
environment = dict(os.environ,PGPASSWORD=opt['db_password'])
subprocess.run([str(pg/'pg_dump.exe'),*connection_args,'-Fc','-f',str(dump),opt['db_name']],env=environment,check=True,capture_output=True)
con = psycopg2.connect(host=opt['db_host'],port=opt['db_port'],user=opt['db_user'],password=opt['db_password'],dbname='postgres')
con.autocommit=True
with con.cursor() as cur:
    cur.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(db)))
con.close()
subprocess.run([str(pg/'pg_restore.exe'),*connection_args,'--exit-on-error','--single-transaction','--no-owner','--no-privileges','-d',db,str(dump)],env=environment,check=True,capture_output=True)
opt.update(db_name=db,dbfilter='^'+db+'$',data_dir=str(BASE/'test-data'),logfile=str(BASE/'test-odoo.log'),max_cron_threads='0',http_enable='False')
with (BASE/'test.conf').open('w',encoding='utf-8') as stream: cfg.write(stream)
(BASE/'test-state.json').write_text(json.dumps({'database':db,'config':str(BASE/'test.conf')}),encoding='utf-8')
print('SAGA_TEST_DATABASE_READY',db)

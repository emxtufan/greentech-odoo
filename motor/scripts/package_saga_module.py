"""Self-contained native updater, with no accounting data or credentials."""
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
addon=ROOT/'custom_addons/greentech_saga_import'
output=ROOT/'logs/saga-deploy'
output.mkdir(parents=True,exist_ok=True)
buffer=io.BytesIO()
names=[]
with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as package:
    for path in sorted(addon.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix not in {'.py','.ps1','.xml','.csv','.md','.js'}:
            continue
        name='greentech_saga_import/'+path.relative_to(addon).as_posix()
        package.write(path,name)
        names.append(name)
    package.write(ROOT/'deploy/financiar/saga-reader-smoke.fdb','reader-smoke.fdb')
    names.append('reader-smoke.fdb')
payload=buffer.getvalue()
with zipfile.ZipFile(io.BytesIO(payload)) as check:
    assert check.testzip() is None
    assert set(check.namelist())==set(names)
    assert not any('cont_baza' in name or '/config/' in name for name in names)
template=(ROOT/'deploy/financiar/update_saga_template.py').read_text(encoding='utf-8')
text=template.replace('__PAYLOAD__',base64.b64encode(payload).decode()).replace('__PAYLOAD_SHA256__',hashlib.sha256(payload).hexdigest())
ast.parse(text)
target=output/'actualizeaza-import-saga.py'
target.write_text(text,encoding='utf-8')
digest=hashlib.sha256(target.read_bytes()).hexdigest()
(output/'actualizeaza-import-saga.py.sha256').write_text(digest+'  '+target.name+'\n',encoding='ascii')
info={'path':str(target),'bytes':target.stat().st_size,'sha256':digest,'files':names,
      'contains_user_database':False,'contains_credentials':False,'linux_execution_verified':False}
(output/'manifest.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
print(json.dumps({k:info[k] for k in ['path','bytes','sha256','contains_user_database','linux_execution_verified']}))

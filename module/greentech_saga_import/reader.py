import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def extract(raw, data_dir):
    if len(raw) < 4096 or len(raw) > 256*1024*1024:
        raise ValueError('Fișierul trebuie să fie un backup .fdb între 4 KB și 256 MB.')
    ods = struct.unpack_from('<H',raw,18)[0] & 0x7fff
    if raw[0] != 1 or ods != 12:
        raise ValueError('Format nesuportat. Este necesar un fișier Firebird 3 / ODS 12, nu o arhivă redenumită .fdb.')
    base = Path(data_dir)/'saga_import_tmp'
    base.mkdir(mode=0o700,parents=True,exist_ok=True)
    helper = Path(__file__).parent/'reader'
    with tempfile.TemporaryDirectory(prefix='read-',dir=base) as temporary:
        temp = Path(temporary)
        database = temp/'source.fdb'
        database.write_bytes(raw)
        output = temp/'extracted'
        if os.name == 'nt':
            command = ['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(helper/'extract.ps1'),'-Database',str(database),'-OutputDirectory',str(output)]
        else:
            command = [sys.executable,'-I',str(helper/'extract_linux.py'),str(database),str(output)]
        try:
            result = subprocess.run(command,capture_output=True,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except subprocess.TimeoutExpired:
            raise ValueError('Citirea backupului a depășit patru minute. Nicio înregistrare contabilă nu a fost importată.') from None
        if result.returncode:
            # No connection settings, payroll values or source payload in browser errors.
            raise ValueError('Citirea Firebird a eșuat. Administratorul trebuie să verifice motorul Firebird 3 embedded și cititorul Python fdb (Linux) / componentele SAGA (Windows). Backupul nu a fost importat.')
        counts = json.loads((output/'counts.json').read_text(encoding='utf-8-sig'))
        data = {}
        if sum(counts.values()) > 250000:
            raise ValueError('Backupul depășește limita de 250.000 de înregistrări pentru importul interactiv.')
        for table, count in counts.items():
            data[table] = [json.loads(line) for line in (output/(table+'.jsonl')).read_text(encoding='utf-8-sig').splitlines()]
            if len(data[table]) != count:
                raise ValueError('Numărul de înregistrări extrase nu corespunde sursei: '+table)
        return data, hashlib.sha256(raw).hexdigest()

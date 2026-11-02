"""Materialize pinned OCA source files retrieved using the GitHub connector."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
count = 0
for bundle in sorted((ROOT / 'logs').glob('oca-financial-source-*.json')):
    for item in json.loads(bundle.read_text(encoding='utf-8')):
        data = item['content'].encode('utf-8')
        digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if digest != item['sha']:
            raise RuntimeError('Source integrity mismatch: ' + item['path'])
        base = (ROOT / 'third_party_addons' / item['repo']).resolve()
        target = (base / item['path']).resolve()
        if not target.is_relative_to(base):
            raise RuntimeError('Invalid path')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        count += 1
print(f'Verified and extracted {count} OCA files.')

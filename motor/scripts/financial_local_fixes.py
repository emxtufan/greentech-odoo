"""Small, documented compatibility/translation fixes over the pinned OCA sources."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = ROOT / 'third_party_addons/account-financial-reporting/account_financial_report'
changes = []

def patch(path, transform):
    raw = path.read_bytes()
    updated = transform(raw.decode('utf-8')).encode('utf-8')
    backup = ROOT / 'logs' / (path.name + '.before-financial-fixes')
    if not backup.exists():
        backup.write_bytes(raw)
    if updated != raw:
        path.write_bytes(updated)
    changes.append({'file': str(path.relative_to(ROOT)),
        'original_sha256': hashlib.sha256(backup.read_bytes()).hexdigest(),
        'patched_sha256': hashlib.sha256(updated).hexdigest()})

patch(base / 'report/templates/journal_ledger.xml', lambda x: x.replace('t-eval="None"','t-value="None"').replace('t-eval="True"','t-value="True"'))
terms = {
    'C??tre':'Către', 'c??tre':'către', 'suplimentar??':'suplimentară',
    '??nregistr??rile':'înregistrările', '??nregistr??ri':'Înregistrări', '??nregistrare':'Înregistrare',
    'Sum?? Valut??':'Sumă valută', 'baz??':'bază', 'Centraliza??i':'Centralizați',
    'P??n??':'Până', 'afi??at':'afișat', 'Dat??':'Dată', 'scadent??':'scadentă',
    'dup??':'după', 'Num??r':'Număr', 'Exporta??i':'Exportați', 'Filtra??i':'Filtrați',
    'Filtreaz??':'Filtrează', 'Moned?? str??in??':'Monedă străină', 'Intr??ri':'Înregistrări',
    'ini??ial':'inițial', 'dat??':'dată', 'Limita??i':'Limitați', 'Mi??c??ri':'Mișcări',
    '??int??':'țintă', 'limit??':'limită', 'Pozi??ii':'Poziții', 'Deschide??i':'Deschideți',
    'Op??iuni':'Opțiuni', 'pl??tit':'plătit', '??ncasat':'încasat', 'Referin????':'Referință',
    'Raporta??i ac??iunea':'Acțiune raport', 'Secven????':'Secvență',
    'Afi??are':'Afișare', 'Afi??a??i':'Afișați', 'mi??care':'mișcare',
    'moned?? str??in??':'monedă străină', 'Sorta??i':'Sortați', 'intr??rile':'înregistrările', '??ntr-un':'într-un',
    'Tax??':'Taxă', 'tax??':'taxă', 's?? fie':'să fie', 'Balan????':'Balanță',
    'l????ime: 23,24%;':'width: 23.24%;', 'l????ime: 23,78%;':'width: 23.78%;',
    'l????ime: 38,92%;':'width: 38.92%;', 'l????ime: 8,11%;':'width: 8.11%;',
}
def fix_translation(text):
    lines = []
    for line in text.splitlines(keepends=True):
        if line.startswith('msgstr '):
            for old, new in terms.items():
                line = line.replace(old, new)
            if '??' in line:
                raise RuntimeError('Unresolved translation: ' + line)
        lines.append(line)
    return ''.join(lines)
patch(base / 'i18n/ro.po', fix_translation)
(ROOT / 'logs/financial-local-patches.json').write_text(json.dumps(changes,indent=2),encoding='utf-8')
print('Applied journal QWeb compatibility and Romanian translation fixes.')

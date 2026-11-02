"""Financial fail-closed regression cases using the supplied source snapshot."""
import copy
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
core = runpy.run_path(str(ROOT/'custom_addons/greentech_saga_import/core.py'))
source = {p.stem:[json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()]
          for p in (ROOT/'logs/saga-migration/extracted').glob('*.jsonl')}
checks=[]
result=core['analyze'](source)
assert not result['errors'],result['errors']
assert (result['native_invoices'],result['historical_documents'])==(88,23)
checks.append('full_source_supported_with_cash_and_self_offset_documents')

def rejects(label, mutate):
    data=copy.deepcopy(source)
    mutate(data)
    assert core['analyze'](data)['errors'],label
    checks.append(label)

rejects('one_cent_invoice_line_mismatch',lambda d:d['INTR_DET'][0].update(TOTAL='310.02'))
rejects('missing_partner',lambda d:d.update(CLIENTI=[]))
rejects('missing_mandatory_table',lambda d:d.pop('REGISTRU'))
rejects('foreign_currency_not_silently_dropped',lambda d:d['REGISTRU'][0].update(COD_VALUTA='EUR',SUMA_VAL='10'))
rejects('unsupported_vat_blocks',lambda d:d['INTRARI'][0].update(TVA='10'))
rejects('unsupported_stock_blocks',lambda d:d.update(ARTICOLE=[{'COD':'A'}]))
rejects('payroll_details_require_full_mapping',lambda d:d.update(SS=[{'COD':'1'}]))
rejects('broken_payment_link',lambda d:d['NOTE_FACTURI'][0].update(ID_NOTA=999999))
rejects('compound_entry_missing_side',lambda d:d['REGISTRU'].pop(next(i for i,r in enumerate(d['REGISTRU']) if r['PK']==119)))
rejects('unexplained_residual',lambda d:d['IESIRI'][0].update(NEACHITAT='1'))
rejects('duplicate_invoice_id',lambda d:d['IESIRI'].append(copy.deepcopy(d['IESIRI'][0])))
checks.append('source_not_mutated')
assert not core['analyze'](source)['errors']
(ROOT/'logs/saga-migration/core-tests.json').write_text(json.dumps({'passed':len(checks),'checks':checks},indent=2),encoding='utf-8')
print('SAGA_CORE_TESTS_OK',len(checks))

"""Read-only preflight of the SAGA extraction; never connects to Odoo."""
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'logs/saga-migration'
EXTRACT = BASE / 'extracted'
D = lambda value: Decimal(str(value or '0'))


def rows(name):
    return [json.loads(line) for line in (EXTRACT / (name + '.jsonl')).read_text(encoding='utf-8').splitlines()]


def main():
    manifest = json.loads((BASE / 'source-manifest.json').read_text(encoding='utf-8-sig'))
    assert hashlib.sha256(Path(manifest['source']).read_bytes()).hexdigest().upper() == manifest['sha256']
    counts = json.loads((EXTRACT / 'counts.json').read_text(encoding='utf-8'))
    for item in json.loads((EXTRACT / 'sha256.json').read_text(encoding='utf-8')):
        assert hashlib.sha256((EXTRACT / item['name']).read_bytes()).hexdigest().upper() == item['sha256']
    for table, count in counts.items():
        assert len(rows(table)) == count, table

    issues = []
    invoice_summary = {}
    register = rows('REGISTRU')
    ledger_by_document = defaultdict(list)
    for line in register:
        ledger_by_document[(line['FEL_D'].strip(), line['ID_NOTA'])].append(line)
    payment_links = defaultdict(list)
    for line in rows('NOTE_FACTURI'):
        payment_links[line['ID_FACTURA']].append(line)
    ledger_ids = {line['ID_NOTA'] for line in register}
    for link in rows('NOTE_FACTURI'):
        if link['ID_NOTA'] not in ledger_ids:
            issues.append({'kind': 'payment_missing_register', 'pk': link['PK'], 'id': link['ID_NOTA']})

    all_invoice_ids = set()
    for table, detail_table, key, party_table, category in [
        ('INTRARI', 'INTR_DET', 'ID_INTRARE', 'FURNIZORI', 'Intrari'),
        ('IESIRI', 'IES_DET', 'ID_IESIRE', 'CLIENTI', 'Iesiri'),
    ]:
        documents, details = rows(table), rows(detail_table)
        parties = {row['COD'].strip() for row in rows(party_table)}
        detail_map = defaultdict(list)
        for detail in details:
            detail_map[detail[key]].append(detail)
        by_year = defaultdict(lambda: {'documents': 0, 'total': Decimal(0), 'unpaid': Decimal(0)})
        document_ids = [doc[key] for doc in documents]
        assert len(set(document_ids)) == len(document_ids), (table, 'duplicate_document_ids')
        all_invoice_ids.update(document_ids)
        for doc in documents:
            docid = doc[key]
            year = doc['DATA'][:4]
            by_year[year]['documents'] += 1
            by_year[year]['total'] += D(doc['TOTAL'])
            by_year[year]['unpaid'] += D(doc['NEACHITAT'])
            if doc['COD'].strip() not in parties:
                issues.append({'kind': 'missing_partner', 'table': table, 'id': docid})
            line_total = sum((D(x['TOTAL']) for x in detail_map[docid]), Decimal(0))
            if line_total != D(doc['TOTAL']):
                issues.append({'kind': 'invoice_lines_total', 'table': table, 'id': docid, 'header': D(doc['TOTAL']), 'lines': line_total})
            register_total = sum((D(x['SUMA']) for x in ledger_by_document[(category, docid)]), Decimal(0))
            if register_total != D(doc['TOTAL']):
                issues.append({'kind': 'invoice_register_total', 'table': table, 'id': docid, 'header': D(doc['TOTAL']), 'register': register_total})
            paid = sum((D(x['SUMA']) for x in payment_links[docid]), Decimal(0))
            remaining = D(doc['TOTAL']) - paid
            if remaining != D(doc['NEACHITAT']):
                issues.append({'kind': 'payment_links_residual', 'table': table, 'id': docid, 'expected_unpaid': D(doc['NEACHITAT']), 'from_links': remaining})
        for detail in details:
            if detail[key] not in document_ids:
                issues.append({'kind': 'orphan_invoice_line', 'table': detail_table, 'id': detail[key]})
        invoice_summary[table] = dict(by_year)
    for link in rows('NOTE_FACTURI'):
        if link['ID_FACTURA'] not in all_invoice_ids:
            issues.append({'kind': 'payment_missing_invoice', 'pk': link['PK'], 'id': link['ID_FACTURA']})

    # Debit/credit are derived once from the full source journal. Invoice and
    # payroll entries must not be added again on top of these source entries.
    ledger = defaultdict(lambda: {'debit': Decimal(0), 'credit': Decimal(0)})
    for line in register:
        year = line['DATA'][:4]
        amount = D(line['SUMA'])
        ledger[(year, line['CONT_D'].strip())]['debit'] += amount
        ledger[(year, line['CONT_C'].strip())]['credit'] += amount
    balance = [{'year': year, 'account': account, **amounts, 'balance': amounts['debit']-amounts['credit']} for (year, account), amounts in sorted(ledger.items())]
    assert sum((x['balance'] for x in balance), Decimal(0)) == 0
    same_account = [x for x in register if x['CONT_D'].strip() == x['CONT_C'].strip()]
    summary = {
        'status': 'preflight_only_not_imported', 'source_sha256': manifest['sha256'],
        'source_unchanged': True, 'all_table_counts_verified': True,
        'company_tax_id': rows('SOCIET')[0]['CODF_S'].strip(),
        'tables': len(counts), 'rows': sum(counts.values()),
        'journal_date_min': min(x['DATA'][:10] for x in register),
        'journal_date_max': max(x['DATA'][:10] for x in register),
        'source_last_closed_date': rows('SOCIET')[0]['DATA_INCH'][:10],
        'invoices': invoice_summary,
        'same_account_journal_rows': len(same_account),
        'same_account_purchase_ids': [x['ID_NOTA'] for x in same_account if x['FEL_D'].strip() == 'Intrari'],
        'payroll_periods': len(rows('STATE')), 'payroll_detail_rows_SS': len(rows('SS')),
        'issue_counts': dict(Counter(x['kind'] for x in issues)), 'issues': issues,
        'required_before_import': ['Confirm company name and CUI', 'Confirm source is a consistent backup', 'Resolve payment and document mapping exceptions', 'Preserve source journal without duplicate invoice/payroll postings', 'Determine whether external payroll details and attachments exist'],
    }
    for name, data in [('audit.json', summary), ('source-ledger-by-year.json', balance)]:
        (BASE / name).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    labels = {'FURNIZORI':'Furnizori', 'CLIENTI':'Clienți', 'INTRARI':'Documente intrare', 'IESIRI':'Documente ieșire', 'INTR_DET':'Linii intrări', 'IES_DET':'Linii ieșiri', 'REGISTRU':'Poziții registru', 'NOTE_FACTURI':'Legături plăți/facturi', 'CONTURI':'Poziții plan conturi', 'PVR':'Imobilizări', 'SALARIATI':'Salariați', 'STATE':'State salariale (antete)', 'SS':'Detalii salariale SS', 'DIURNE':'Diurne'}
    table_html = ''.join(f'<tr><td>{label}</td><td>{counts[name]}</td></tr>' for name, label in labels.items())
    result = f'''<!doctype html><html lang="ro"><meta charset="utf-8"><title>Verificare migrare SAGA</title>
<style>body{{font:16px system-ui;max-width:1000px;margin:40px auto;color:#20362c}}table{{border-collapse:collapse;width:100%}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}pre{{white-space:pre-wrap;background:#f4f6f5;padding:16px}}.status{{background:#fff2cc;padding:18px}}</style>
<h1>Inventar SAGA pentru migrare</h1><p class="status">Date extrase și verificate. Nu s-a făcut niciun import în Odoo și nu s-a modificat serverul.</p>
<p>CUI din sursă: <b>{html.escape(summary['company_tax_id'])}</b>. Denumirea firmei necesită confirmare.</p>
<p>Registru: {summary['journal_date_min']} – {summary['journal_date_max']}. Ultima închidere indicată în SAGA: {summary['source_last_closed_date']}.</p>
<p>{len(counts)} tabele, {sum(counts.values())} înregistrări. Numărul extras din fiecare tabel a fost comparat cu COUNT(*) în aceeași tranzacție numai pentru citire.</p>
<table><tr><th>Categorie</th><th>Înregistrări</th></tr>{table_html}</table>
<h2>Totaluri documente</h2><pre>{html.escape(json.dumps(invoice_summary,indent=2,ensure_ascii=False,default=str))}</pre>
<h2>Aspecte de rezolvat</h2><p>Două documente de intrare sunt operate pe contul de cheltuială 6022 și produc debit/credit pe același cont. Nu vor fi transformate automat în datorii la furnizori. Există antete de state salariale, dar tabelul SS nu conține detalii. Fișierul nu demonstrează existența PDF-urilor, XML-urilor și recipiselor externe.</p>
<p>Registrul conține deja facturile, amortizarea, salariile și închiderile. Importarea lor încă o dată ar dubla contabilitatea.</p>
<pre>{html.escape(json.dumps(summary['issue_counts'],indent=2))}</pre>
<p>Inventarul integral și toate datele extrase rămân local, în directorul logs/saga-migration. Nu publicați acest director: conține date contabile și personale.</p></html>'''
    (BASE / 'raport-verificare.html').write_text(result, encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ['status','tables','rows','company_tax_id','invoices','issue_counts','same_account_purchase_ids']},default=str))


if __name__ == '__main__':
    main()

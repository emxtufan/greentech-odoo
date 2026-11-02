"""Pure, exact-decimal interpretation of the supported SAGA source schema."""
from collections import defaultdict, Counter
from decimal import Decimal
import hashlib
import json
import re


def number(value):
    return Decimal(str(value or '0'))


def clean(value):
    return str(value or '').strip()


def date(value):
    return clean(value)[:10] or False


def tax_id(value):
    return re.sub(r'\D', '', clean(value))


def ledger_key(row):
    return (clean(row['FEL_D']), row['ID_NOTA'], date(row['DATA']))


def normalized_ledger(rows):
    """SAGA compound entries use % and blank sides: they are not accounts."""
    groups = defaultdict(list)
    for row in rows:
        for side, field in [('debit','CONT_D'),('credit','CONT_C')]:
            account = clean(row[field])
            if account in ('', '%'):
                continue
            groups[ledger_key(row)].append({'account':account,'side':side,'amount':number(row['SUMA']),'row':row})
    return groups


def mapped_invoice_lines(doc, lines, journal_rows, purchase):
    remaining = list(journal_rows)
    result = []
    for line in lines:
        side, other = ('CONT_D','CONT_C') if purchase else ('CONT_C','CONT_D')
        counter = clean(doc['CONT_FUR' if purchase else 'CONT_CLI'])
        candidates = [r for r in remaining if number(r['SUMA'])==number(line['TOTAL']) and clean(r[other])==counter]
        exact = [r for r in candidates if clean(r[side])==clean(line['CONT'])]
        if exact:
            selected = exact[0]
        elif len(candidates)==1 and clean(candidates[0][side]).startswith(clean(line['CONT'])):
            selected = candidates[0]  # SAGA journal records the actual analytic account.
        else:
            raise ValueError('Cont de linie ambiguu sau necorelat cu registrul.')
        remaining.remove(selected)
        result.append((line,clean(selected[side])))
    if remaining:
        raise ValueError('Poziții de registru fără linie de factură.')
    return result


def analyze(data):
    errors = []
    notes = []
    required = ['SOCIET','CONTURI','FURNIZORI','CLIENTI','INTRARI','INTR_DET','IESIRI','IES_DET','REGISTRU','NOTE_FACTURI']
    missing = set(required) - set(data)
    if missing:
        return {'errors': ['Tabele obligatorii lipsă: ' + ', '.join(sorted(missing))], 'notes': [], 'counts': {k:len(v) for k,v in data.items()}}
    if len(data['SOCIET']) != 1:
        errors.append('Backupul trebuie să conțină exact o societate.')
    cui = tax_id(data['SOCIET'][0].get('CODF_S')) if data['SOCIET'] else ''
    if not cui:
        errors.append('CUI lipsă în SOCIET.CODF_S. Nu se ghicește firma.')
    ledger = data['REGISTRU']
    if not ledger:
        errors.append('Registrul contabil este gol; profilul de import cu istoric nu se aplică.')
    if any(clean(x.get('COD_VALUTA')) not in ('', 'RON', 'LEI') or number(x.get('SUMA_VAL')) for x in ledger):
        errors.append('Există operațiuni în valută. Maparea valutară trebuie extinsă înainte de import.')
    groups = defaultdict(list)
    account_totals = defaultdict(lambda: [Decimal(0),Decimal(0)])
    for row in ledger:
        groups[ledger_key(row)].append(row)
        for key in ['CONT_D','CONT_C']:
            if clean(row[key]) not in ('','%') and not re.fullmatch(r'[0-9][0-9A-Za-z.\-_]*', clean(row[key])):
                errors.append('Cont invalid în registru: ' + clean(row[key]))
        amount = number(row['SUMA'])
        account_totals[(date(row['DATA'])[:4], clean(row['CONT_D']))][0] += amount
        account_totals[(date(row['DATA'])[:4], clean(row['CONT_C']))][1] += amount
    for key, lines in normalized_ledger(ledger).items():
        if sum((x['amount']*(1 if x['side']=='debit' else -1) for x in lines),Decimal(0)):
            errors.append('Notă contabilă dezechilibrată după interpretarea formulei compuse: '+str(key))
    # A NOTE_FACTURI row must resolve to exactly one journal group, never a guessed match.
    payment_groups = defaultdict(list)
    for key in groups:
        payment_groups[key[1]].append(key)
    links = defaultdict(list)
    for row in data['NOTE_FACTURI']:
        links[row['ID_FACTURA']].append(row)
        if len(payment_groups[row['ID_NOTA']]) != 1:
            errors.append('Plată cu legătură ambiguă în registru: ' + str(row['ID_NOTA']))
        if number(row.get('TVAINC')) or number(row.get('TVA_P')):
            errors.append('TVA la încasare/plată necesită mapare suplimentară.')
    docs = []
    known_ids = set()
    native_ids = set()
    for table, line_table, idkey, counterkey, category, partners in [
        ('INTRARI','INTR_DET','ID_INTRARE','CONT_FUR','Intrari','FURNIZORI'),
        ('IESIRI','IES_DET','ID_IESIRE','CONT_CLI','Iesiri','CLIENTI')]:
        line_map = defaultdict(list)
        for line in data[line_table]:
            line_map[line[idkey]].append(line)
        party_codes = {clean(p['COD']) for p in data[partners]}
        table_ids = set()
        for row in data[table]:
            docid = row[idkey]
            if docid in known_ids:
                errors.append('Identificator de document duplicat: '+str(docid))
            known_ids.add(docid)
            table_ids.add(docid)
            label = f'{table} / {docid}'
            if clean(row['COD']) not in party_codes:
                errors.append(label + ': partener lipsă.')
            if clean(row.get('VALIDAT')) != 'V' or clean(row.get('TIP')):
                errors.append(label + ': document nevalidat sau tip special neimplementat.')
            if number(row['TVA']) or row.get('TVAI'):
                errors.append(label + ': TVA necesită mapare fiscală înainte de import.')
            if number(row['TOTAL']) <= 0:
                errors.append(label + ': storno/valoare zero necesită profil separat.')
            lines = line_map[docid]
            if not lines or sum((number(x['TOTAL']) for x in lines), Decimal(0)) != number(row['TOTAL']):
                errors.append(label + ': liniile nu corespund totalului.')
            if any(number(x.get('TVA_DED')) or number(x.get('TVA_ART')) or number(x.get('TRANSP_LEI')) or number(x.get('DISCOUNT')) for x in lines):
                errors.append(label + ': taxe/transport/discount separat necesită profil suplimentar.')
            for line in lines:
                if number(line['CANTITATE']) <= 0 or abs(number(line['CANTITATE'])*number(line['PRET_UNITAR']) - number(line['TOTAL'])) > Decimal('0.005'):
                    errors.append(label + ': cantitate/preț necorelat.')
            key = (category, docid, date(row['DATA']))
            journal_rows = groups.get(key, [])
            if len(journal_rows) != len(lines) or sum((number(x['SUMA']) for x in journal_rows), Decimal(0)) != number(row['TOTAL']):
                errors.append(label + ': registrul nu corespunde liniilor documentului.')
            counter = clean(row[counterkey])
            expected_pairs = Counter((clean(x['CONT']),counter,str(number(x['TOTAL']))) if table=='INTRARI' else (counter,clean(x['CONT']),str(number(x['TOTAL']))) for x in lines)
            actual_pairs = Counter((clean(x['CONT_D']),clean(x['CONT_C']),str(number(x['SUMA']))) for x in journal_rows)
            try:
                mapped_invoice_lines(row,lines,journal_rows,table=='INTRARI')
                if expected_pairs != actual_pairs:
                    notes.append(label + ': contul analitic este preluat din registrul contabil.')
            except ValueError as exc:
                errors.append(label + ': ' + str(exc))
            native = counter.startswith('401') if table=='INTRARI' else counter.startswith('411')
            paid = sum((number(x['SUMA']) for x in links[docid]),Decimal(0))
            residual = number(row['TOTAL']) - paid
            if native:
                native_ids.add(docid)
                if residual != number(row['NEACHITAT']):
                    errors.append(label + ': legăturile de plată nu explică soldul.')
            elif table == 'IESIRI' and counter.startswith('53') and not number(row['NEACHITAT']):
                notes.append(label + ': încasare direct în casă, document istoric cu notă contabilă, fără creanță fictivă.')
            elif table == 'INTRARI' and all(clean(x['CONT_D'])==clean(x['CONT_C']) for x in journal_rows):
                notes.append(label + ': debit/credit pe același cont în SAGA; păstrat exact, fără datorie nouă.')
            else:
                errors.append(label + ': cont de contraparte nesuportat: ' + counter)
            docs.append({'table':table,'id':docid,'key':key,'native':native,'row':row,'lines':lines,'counter':counter})
        if set(line_map)-table_ids:
            errors.append(line_table + ': linii fără document.')
    for invoice_id, rows in links.items():
        if invoice_id not in known_ids:
            errors.append('Plată fără document: '+str(invoice_id))
    # Cash and self-offset documents have no Odoo receivable/payable to reconcile.
    for invoice_id in set(links)-native_ids:
        if links[invoice_id]:
            notes.append('Legături istorice păstrate pentru documentul direct '+str(invoice_id)+'.')
    if data.get('STATE') and not data.get('SS'):
        notes.append('Există antete de state, dar SS este gol. Se păstrează istoricul și notele salariale, fără inventarea fluturașilor.')
    if data.get('SS') or data.get('DIURNE') or data.get('ARTICOLE') or data.get('MISCARI'):
        errors.append('Detalii salariale/diurne/stocuri prezente: profilul operațional trebuie extins. Nu se importă parțial contabilitatea.')
    notes.append('Imobilizările sunt preluate ca registru istoric cu valorile SAGA. Nu se regenerează automat amortizarea deja contabilizată.')
    totals = {t:{'count':len(data[t]),'total':str(sum((number(r['TOTAL']) for r in data[t]),Decimal(0))),'unpaid':str(sum((number(r['NEACHITAT']) for r in data[t]),Decimal(0)))} for t in ['INTRARI','IESIRI']}
    return {'cui':cui,'errors':list(dict.fromkeys(errors)),'notes':notes,'counts':{k:len(v) for k,v in data.items()},'totals':totals,
            'native_invoices':sum(d['native'] for d in docs),'historical_documents':sum(not d['native'] for d in docs),
            'period_start':min((date(x['DATA']) for x in ledger),default=False),'period_end':max((date(x['DATA']) for x in ledger),default=False)}

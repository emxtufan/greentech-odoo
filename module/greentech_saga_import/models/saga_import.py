import base64
from collections import defaultdict
from decimal import Decimal
import hashlib
import html
import json
import logging
import re

from odoo import api, fields, models, Command
from odoo.exceptions import UserError, AccessError
from odoo.tools import config
from ..core import analyze, clean, date, ledger_key, mapped_invoice_lines, normalized_ledger, number, tax_id
from ..reader import extract

_logger = logging.getLogger(__name__)
_INTERNAL = object()


class SagaBatch(models.Model):
    _name = 'saga.import.batch'
    _description = 'Import backup SAGA'
    _order = 'id desc'

    name = fields.Char(string='Denumirea firmei', required=True)
    expected_cui = fields.Char(string='CUI confirmat', required=True)
    registry_number = fields.Char(string='Nr. Registrul Comerțului')
    euid = fields.Char(string='EUID')
    street = fields.Char(string='Adresă sediu')
    city = fields.Char(string='Localitate')
    source_file = fields.Binary(string='Backup SAGA (.fdb)', attachment=True, groups='base.group_system')
    filename = fields.Char()
    owner_company_id = fields.Many2one('res.company', default=lambda self:self.env.company, required=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Firma importată', readonly=True)
    source_hash = fields.Char(string='SHA256 backup', readonly=True, index=True)
    state = fields.Selection([('draft','Fișier nou'),('ready','Verificat'),('blocked','Necesită verificare'),('done','Importat'),('failed','Import anulat')],default='draft',readonly=True)
    report = fields.Html(string='Rezultat',readonly=True)
    extracted = fields.Binary(attachment=True, readonly=True, groups='base.group_system')
    result_json = fields.Json(readonly=True, groups='base.group_system')
    imported_at = fields.Datetime(readonly=True)
    document_ids = fields.One2many('saga.document','batch_id',string='Documente')
    source_confirmed = fields.Boolean(string='Confirm că fișierul este un backup consistent și firma este corectă')

    existing_batch_id = fields.Many2one('saga.import.batch', compute='_compute_existing_batch', string='Import existent')

    @api.depends('source_hash', 'state')
    def _compute_existing_batch(self):
        for batch in self:
            batch.existing_batch_id = batch if batch.state == 'done' else (
                self.search([('source_hash', '=', batch.source_hash), ('state', '=', 'done')], limit=1)
                if batch.source_hash else False)

    def action_open_work(self):
        self.ensure_one()
        self._manager()
        batch = self.existing_batch_id
        if not batch:
            raise UserError('Firma nu a fost încă importată.')
        company = batch.company_id
        if company not in self.env.user.company_ids:
            raise AccessError('Nu ai acces la firma importată.')
        targets = {'customers', 'vendors', 'sales', 'purchases', 'banks', 'ledger', 'partners', 'employees', 'statements'}
        target = self.env.context.get('saga_screen', 'banks')
        if target not in targets:
            raise UserError('Ecran necunoscut.')
        return {'type': 'ir.actions.client', 'tag': 'greentech_saga_open_company',
                'params': {'company_id': company.id,
                           'action_id': self.env.ref('greentech_saga_import.work_' + target).id}}

    def _prepare_operations(self):
        """Configure native journals/payment clearing; never create accounting entries."""
        self.ensure_one()
        company = self.company_id
        scoped = self.with_company(company).with_context(allowed_company_ids=[company.id])
        env = scoped.env
        env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['saga-operations:' + str(company.id)])
        liquidity = env['account.move.line'].search([
            ('move_id.saga_batch_id', '=', self.id), ('account_id.account_type', '=', 'asset_cash')]).account_id
        journals = env['account.journal']
        for account in liquidity.sorted('code'):
            kind = 'cash' if account.code.startswith('53') else 'bank'
            journal = env['account.journal'].search([
                ('company_id', '=', company.id), ('default_account_id', '=', account.id), ('type', '=', kind)], limit=1)
            if not journal:
                # Stable account-based identity, independently of the journal's display name.
                index = 1
                while env['account.journal'].search_count([('company_id', '=', company.id), ('code', '=', 'SG' + str(index))]):
                    index += 1
                journal = env['account.journal'].create({'name': account.code + ' - ' + account.name,
                    'code': 'SG' + str(index), 'type': kind, 'company_id': company.id, 'default_account_id': account.id})
            journals |= journal
            methods = journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids
            for method in methods.filtered(lambda m: not m.payment_account_id):
                if kind == 'cash':
                    clearing = account
                else:
                    inbound = method.payment_type == 'inbound'
                    code = '5125.SGI' if inbound else '5125.SGO'
                    clearing = env['account.account'].search([('company_ids', 'in', [company.id]), ('code', '=', code)], limit=1)
                    if not clearing:
                        clearing = env['account.account'].create({'code': code,
                            'name': 'Încasări în curs de decontare' if inbound else 'Plăți în curs de decontare',
                            'account_type': 'asset_current', 'reconcile': True, 'company_ids': [Command.set([company.id])]})
                method.payment_account_id = clearing
        # The Romanian template creates an empty generic bank journal on 512101.
        # Hide only that untouched placeholder, so future payments use source accounts.
        placeholders = env['account.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'BNK1'), ('type', '=', 'bank'),
            ('default_account_id', 'not in', liquidity.ids)])
        for placeholder in placeholders:
            if (not placeholder.bank_account_id
                    and not env['account.move'].search_count([('journal_id', '=', placeholder.id)])
                    and not env['account.payment'].search_count([('journal_id', '=', placeholder.id)])
                    and not env['account.bank.statement.line'].search_count([('journal_id', '=', placeholder.id)])
                    and not env['account.move.line'].search_count([('account_id', '=', placeholder.default_account_id.id)])):
                placeholder.active = False
        return journals

    def _manager(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError('Importul unei firme este disponibil numai administratorilor.')

    @api.model_create_multi
    def create(self, vals_list):
        self._manager()
        for vals in vals_list:
            forbidden = {'company_id','state','extracted','source_hash','result_json','report','imported_at'} & vals.keys()
            if forbidden and self.env.context.get('_saga_internal') is not _INTERNAL:
                raise AccessError('Rezultatele importului sunt calculate de modul.')
        return super().create(vals_list)

    def write(self, vals):
        self._manager()
        if self.env.context.get('_saga_internal') is not _INTERNAL:
            if any(x.state=='done' for x in self):
                raise UserError('Importul finalizat este păstrat pentru audit și nu se modifică.')
            if {'company_id','owner_company_id','state','extracted','source_hash','result_json','report','imported_at'} & vals.keys():
                raise AccessError('Rezultatele importului sunt calculate de modul.')
            if {'source_file','expected_cui'} & vals.keys():
                vals = dict(vals,state='draft',extracted=False,source_hash=False,result_json=False,report=False)
        return super().write(vals)

    def unlink(self):
        if any(x.state=='done' for x in self):
            raise UserError('Importul finalizat nu poate fi șters.')
        return super().unlink()

    def _set(self, **vals):
        return self.with_context(_saga_internal=_INTERNAL).write(vals)

    def _action(self):
        return {'type':'ir.actions.act_window','res_model':self._name,'res_id':self.id,'view_mode':'form','target':'current'}

    def _report_html(self,result,done=False):
        esc = lambda value:html.escape(str(value))
        counts = result.get('counts',{})
        labels = {'FURNIZORI':'Furnizori','CLIENTI':'Clienți','INTRARI':'Documente intrare','IESIRI':'Documente ieșire',
                  'REGISTRU':'Poziții sursă în registru','PVR':'Imobilizări (istoric)','SALARIATI':'Salariați','STATE':'State salariale (antete)'}
        parts = ['<h3>'+('Import verificat' if done else 'Rezultatul analizei')+'</h3>',
                 '<p><b>'+esc(self.name)+'</b> · CUI '+esc(result.get('cui',''))+'</p>',
                 '<p>Perioada registrului: '+esc(result.get('period_start',''))+' – '+esc(result.get('period_end',''))+'</p>',
                 '<table class="table table-sm"><thead><tr><th>Categorie</th><th>Înregistrări</th></tr></thead><tbody>']
        parts += ['<tr><td>'+label+'</td><td>'+str(counts.get(key,0))+'</td></tr>' for key,label in labels.items()]
        parts.append('</tbody></table>')
        if result.get('errors'):
            duplicate_only = len(result['errors']) == 1 and result['errors'][0].startswith('Acest backup a fost deja importat:')
            title = 'Date deja disponibile în firma importată' if duplicate_only else 'Import oprit'
            parts.append('<h4>'+title+'</h4><ul>'+''.join('<li>'+esc(x)+'</li>' for x in result['errors'])+'</ul>')
            if duplicate_only:
                parts.append('<p>Folosește butoanele de lucru de mai sus. Reimportarea este blocată pentru a nu dubla facturile și soldurile.</p>')
        else:
            parts.append('<p>'+str(result.get('native_invoices',0))+' facturi Odoo și '+str(result.get('historical_documents',0))+' documente istorice legate de note contabile. Documentele directe nu creează datorii sau creanțe suplimentare.</p>')
        parts.append('<h4>Totaluri din backup</h4>')
        for key,label in [('INTRARI','Intrări'),('IESIRI','Ieșiri')]:
            total = result.get('totals',{}).get(key,{})
            parts.append('<p>'+label+': <b>'+esc(total.get('total','0'))+' RON</b>; sold SAGA: '+esc(total.get('unpaid','0'))+' RON.</p>')
        if done:
            parts.append('<p><b>Verificare trecută:</b> '+str(result.get('posted_moves',0))+' note contabile; debit și credit identice cu SAGA pentru '+str(result.get('verified_account_year_pairs',0))+' combinații cont/an. Soldurile facturilor sunt reconciliate; supraplățile rămân pe plățile partenerilor.</p>')
            parts.append('<p><b>Datele sunt disponibile pentru lucru.</b> Butoanele de mai sus selectează firma și deschid clienții, furnizorii, facturile și casa/banca. Soldul SAGA de mai jos este cel din backup; situația curentă este în facturile și fișele partenerilor.</p>')
        parts.append('<h4>Ce se păstrează ca istoric</h4><p>Imobilizările și statele salariale păstrează valorile din backup. Nu se recalculează amortizare sau salarii și nu se generează declarații ANAF. Fișierele PDF/XML externe nu se pot recupera dacă nu sunt în backup.</p>')
        if counts.get('STATE') and not counts.get('SS'):
            parts.append('<p><b>Lipsesc detaliile individuale ale statelor:</b> tabelul SS este gol. Antetele și notele salariale sunt păstrate; nu se inventează fluturași.</p>')
        return ''.join(parts)

    def action_analyze(self):
        self.ensure_one()
        self._manager()
        if self.state=='done':
            return self._action()
        if not self.source_file or not self.source_confirmed:
            raise UserError('Încarcă backupul .fdb și confirmă proveniența lui.')
        try:
            raw = base64.b64decode(self.source_file,validate=True)
            data, digest = extract(raw, config['data_dir'])
            result = analyze(data)
            if result.get('cui') != tax_id(self.expected_cui):
                result['errors'].append('CUI-ul din backup diferă de CUI-ul confirmat. Importul este oprit.')
            duplicate = self.search([('source_hash','=',digest),('state','=','done'),('id','!=',self.id)],limit=1)
            if duplicate:
                result['errors'].append('Acest backup a fost deja importat: '+duplicate.name)
            report = self._report_html(result)
            self._set(source_hash=digest,extracted=base64.b64encode(json.dumps(data,ensure_ascii=False).encode()),
                      result_json=result,state='blocked' if result['errors'] else 'ready',report=report)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self._set(state='blocked',report='<p>'+html.escape(str(exc))+'</p>')
        return self._action()

    def action_import(self):
        self.ensure_one()
        self._manager()
        if self.state=='done':
            return self._action()
        if self.state!='ready' or not self.source_confirmed:
            raise UserError('Analizează backupul și rezolvă blocajele înainte de import.')
        if hashlib.sha256(base64.b64decode(self.source_file)).hexdigest()!=self.source_hash:
            raise UserError('Fișierul s-a modificat. Repetă analiza.')
        # Serialize all imports of the same firm, including different source hashes.
        self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['saga:'+tax_id(self.expected_cui)])
        data = json.loads(base64.b64decode(self.extracted))
        check = analyze(data)
        if check['errors'] or check['cui'] != tax_id(self.expected_cui):
            raise UserError('Verificarea datelor nu mai permite importul.')
        try:
            with self.env.cr.savepoint():
                result = self._perform_import(data,check)
                self._set(state='done',result_json=result,imported_at=fields.Datetime.now(),
                          report=self._report_html(result,done=True))
        except Exception as exc:
            _logger.exception('SAGA import batch %s rolled back',self.id)
            self.invalidate_recordset()
            self._set(state='failed',report='<h3>Import anulat integral</h3><p>'+html.escape(str(exc))+'</p><p>Firma și înregistrările create în această încercare au fost anulate. Datele preexistente nu au fost înlocuite. Repetă analiza înainte de o nouă încercare.</p>')
        return self._action()

    def _perform_import(self,data,check):
        cui = check['cui']
        existing = self.env['res.company'].sudo().search([]).filtered(lambda c:tax_id(c.vat)==cui)
        if existing:
            raise UserError('Există deja o firmă cu acest CUI. Importul inițial nu suprascrie o firmă existentă și nu dublează istoricul. Este necesar un flux separat de actualizare incrementală.')
        ro = self.env.ref('base.ro')
        company_values = {'name':self.name,'vat':cui,'company_registry':self.registry_number,
            'country_id':ro.id,'currency_id':self.env.ref('base.RON').id,'street':self.street,'city':self.city,
            'account_storno':True}
        if 'iap_enrich_auto_done' in self.env['res.company']._fields:
            company_values['iap_enrich_auto_done'] = True
        company = self.env['res.company'].create(company_values)
        self.env.user.sudo().write({'company_ids':[Command.link(company.id)]})
        self._set(company_id=company.id)
        scoped = self.with_company(company).with_context(allowed_company_ids=[company.id],tracking_disable=True,mail_create_nosubscribe=True,mail_notify_force_send=False)
        return scoped._load_company(data,check,company)

    def _load_company(self,data,check,company):
        env = self.env
        env['account.chart.template'].try_loading('ro',company,install_demo=False)
        # All native default journals remain available for future transactions.
        def journal(name,code,kind):
            return env['account.journal'].create({'name':name,'code':code,'type':kind,'company_id':company.id})
        sale = journal('SAGA - facturi clienți','SGV','sale')
        purchase = journal('SAGA - facturi furnizori','SGA','purchase')
        general = journal('SAGA - registru istoric','SGI','general')
        chart = {a.code:a for a in env['account.account'].search([('company_ids','in',[company.id])])}
        source_chart = {clean(r['CONT']):r for r in data['CONTURI']}
        normalized = normalized_ledger(data['REGISTRU'])
        required_accounts = {x['account'] for lines in normalized.values() for x in lines}
        required_accounts |= {clean(r['ANALITIC']) for table in ['FURNIZORI','CLIENTI'] for r in data[table] if clean(r['ANALITIC']) not in ('','%')}
        def kind(code):
            if code.startswith('411'): return 'asset_receivable'
            if code.startswith('401'): return 'liability_payable'
            if code.startswith(('51','53')): return 'asset_cash'
            if code.startswith('6'): return 'expense_depreciation' if code.startswith('681') else 'expense'
            if code.startswith('7'): return 'income'
            if code.startswith('1'): return 'equity' if code.startswith(('10','11','12')) else 'liability_non_current'
            if code.startswith('2'): return 'asset_fixed'
            if code.startswith('3'): return 'asset_current'
            if code.startswith(('409','425','4424','4426','461','471')): return 'asset_current'
            # 891 participates in historical opening balances with normal accounts.
            if code.startswith('89'): return 'equity'
            return 'liability_current'
        # Keep the source chart, including unused valid accounts, available.
        for code in sorted(required_accounts | {c for c in source_chart if re.fullmatch(r'[0-9][0-9A-Za-z.\-_]*',c)}):
            if code not in chart:
                parent = next((chart[code[:i]] for i in range(len(code)-1,0,-1) if code[:i] in chart),None)
                account_type = parent.account_type if parent else kind(code)
                if code.startswith(('411','401','51','53','89')):
                    account_type = kind(code)
                chart[code] = env['account.account'].create({'code':code,'name':clean(source_chart.get(code,{}).get('DENUMIRE')) or 'SAGA '+code,
                    'account_type':account_type,'company_ids':[Command.set([company.id])],
                    'reconcile':account_type in ('asset_receivable','liability_payable')})
        for code in required_accounts:
            if code.startswith(('411','401')):
                chart[code].write({'account_type':kind(code),'reconcile':True})
        partners = {}
        by_account = {}
        for table, rank in [('FURNIZORI','supplier_rank'),('CLIENTI','customer_rank')]:
            for row in data[table]:
                code = clean(row['COD'])
                country = env['res.country'].search([('code','=',clean(row.get('TARA')) or 'RO')],limit=1) or env.ref('base.ro')
                values = {'name':clean(row['DENUMIRE']) or table+' '+code,'company_id':company.id,rank:1,
                    'ref':'SAGA/'+table+'/'+code,'vat':clean(row.get('COD_FISCAL')) or False,
                    'company_registry':clean(row.get('REG_COM')),'street':clean(row.get('ADRESA')),
                    'city':clean(row.get('LOCALITATE')),'zip':clean(row.get('COD_POST')),'country_id':country.id,
                    'email':clean(row.get('EMAIL')),'phone':clean(row.get('TEL')),'is_company':bool(clean(row.get('REG_COM')))}
                analytic = clean(row['ANALITIC'])
                if analytic.startswith('401'):
                    values['property_account_payable_id'] = chart[analytic].id
                if analytic.startswith('411'):
                    values['property_account_receivable_id'] = chart[analytic].id
                # Preserve supplied VAT verbatim; legacy records may not pass modern validation.
                partner = env['res.partner'].with_context(no_vat_validation=True).create(values)
                partners[(table,code)] = partner
                if analytic.startswith(('401','411')):
                    if analytic in by_account:
                        raise UserError('Mai mulți parteneri pe același cont analitic: '+analytic)
                    by_account[analytic] = partner
                iban = re.sub(r'\s','',clean(row.get('CONT_BANCA')))
                if iban:
                    env['res.partner.bank'].create({'partner_id':partner.id,'acc_number':iban,'company_id':company.id})

        moves = {}
        docs = {}
        native_docs = {}
        for table,detail_table,keyfield,kind_name in [('INTRARI','INTR_DET','ID_INTRARE','purchase'),('IESIRI','IES_DET','ID_IESIRE','sale')]:
            details = defaultdict(list)
            for line in data[detail_table]: details[line[keyfield]].append(line)
            for row in sorted(data[table],key=lambda x:(x['DATA'],x[keyfield])):
                purchase_doc = table=='INTRARI'
                docid = row[keyfield]
                key = ('Intrari' if purchase_doc else 'Iesiri',docid,date(row['DATA']))
                counter = clean(row['CONT_FUR' if purchase_doc else 'CONT_CLI'])
                native = counter.startswith('401' if purchase_doc else '411')
                partner = partners[('FURNIZORI' if purchase_doc else 'CLIENTI',clean(row['COD']))]
                document = env['saga.document'].create({'batch_id':self.id,'company_id':company.id,'source_id':docid,
                    'kind':kind_name,'name':clean(row['NR_INTRARE' if purchase_doc else 'NR_IESIRE']),
                    'date':date(row['DATA']),'due_date':date(row['SCADENT']),'partner_id':partner.id,
                    'amount_total':float(number(row['TOTAL'])),'source_residual':float(number(row['NEACHITAT'])),
                    'handling':'native' if native else 'historical','source_counterpart':counter,
                    'line_ids':[Command.create({'name':clean(x['DENUMIRE']),'quantity':float(number(x['CANTITATE'])),
                        'price_unit':float(number(x['PRET_UNITAR'])),'amount_total':float(number(x['TOTAL'])),'source_account':clean(x['CONT'])}) for x in details[docid]]})
                docs[docid] = document
                if not native:
                    continue
                source_rows = [x for x in data['REGISTRU'] if ledger_key(x)==key]
                mapped = mapped_invoice_lines(row,details[docid],source_rows,purchase_doc)
                move = env['account.move'].with_context(default_move_type='in_invoice' if purchase_doc else 'out_invoice').create({
                    'company_id':company.id,'journal_id':purchase.id if purchase_doc else sale.id,
                    'move_type':'in_invoice' if purchase_doc else 'out_invoice','partner_id':partner.id,
                    'invoice_date':date(row['DATA']),'date':date(row['DATA']),'invoice_date_due':date(row['SCADENT']),
                    'ref':document.name,'invoice_origin':'SAGA '+table+' '+str(docid),'saga_batch_id':self.id,
                    'invoice_line_ids':[Command.create({'name':clean(line['DENUMIRE']), 'account_id':chart[account].id,
                        'quantity':float(number(line['CANTITATE'])),'price_unit':float(number(line['PRET_UNITAR'])),
                        'tax_ids':[Command.clear()]}) for line,account in mapped]})
                move.action_post()
                if number(str(move.amount_total)).quantize(Decimal('.01')) != number(row['TOTAL']):
                    raise UserError('Total diferit după crearea facturii '+document.name)
                moves[key] = move
                native_docs[docid] = (document,move,row,counter)
                document.move_id = move

        for key, lines in sorted(normalized.items(),key=lambda x:(x[0][2],x[0][1],x[0][0])):
            if key in moves:
                continue
            commands = []
            for item in lines:
                source, code, amount = item['row'],item['account'],item['amount']
                values = {'name':clean(source['EXPLICATIE']) or 'SAGA','account_id':chart[code].id,
                    'balance':float(amount if item['side']=='debit' else -amount), 'is_storno':amount<0,
                    'partner_id':by_account[code].id if code in by_account else False}
                if chart[code].account_type in ('asset_receivable','liability_payable'):
                    values['date_maturity'] = key[2]
                commands.append(Command.create(values))
            move = env['account.move'].create({'company_id':company.id,'journal_id':general.id,'date':key[2],
                'ref':f'SAGA {key[0] or "Notă"} #{key[1]}','saga_batch_id':self.id,'line_ids':commands})
            move.action_post()
            moves[key] = move
        for docid, document in docs.items():
            if not document.move_id:
                key = ('Intrari' if document.kind=='purchase' else 'Iesiri',docid,str(document.date))
                document.move_id = moves[key]

        groups_by_id = defaultdict(list)
        for key in moves: groups_by_id[key[1]].append(key)
        unmatched_overpayments = []
        for link in sorted(data['NOTE_FACTURI'],key=lambda r:(r['DATA'],r['PK'])):
            docid = link['ID_FACTURA']
            if docid not in native_docs:
                continue
            document,invoice,row,counter = native_docs[docid]
            payment = moves[groups_by_id[link['ID_NOTA']][0]]
            invoice_lines = invoice.line_ids.filtered(lambda l:l.account_id==chart[counter])
            payment_lines = payment.line_ids.filtered(lambda l:l.account_id==chart[counter])
            remaining = number(link['SUMA'])
            if remaining < 0:
                raise UserError('Legătură de plată negativă nesuportată: '+str(link['PK']))
            for inv in invoice_lines:
                for pay in payment_lines:
                    inv.invalidate_recordset(['amount_residual'])
                    pay.invalidate_recordset(['amount_residual'])
                    if inv.balance*pay.balance >= 0:
                        continue
                    available = min(abs(number(inv.amount_residual)),abs(number(pay.amount_residual)),remaining)
                    if available <= 0:
                        continue
                    debit,credit = (inv,pay) if inv.balance>0 else (pay,inv)
                    env['account.partial.reconcile'].create({'debit_move_id':debit.id,'credit_move_id':credit.id,
                        'amount':float(available),'debit_amount_currency':float(available),'credit_amount_currency':float(available)})
                    remaining -= available
            if remaining:
                # Negative source residual represents an overpayment, not a negative Odoo invoice.
                if number(row['NEACHITAT']) >= 0:
                    raise UserError('Plata nu poate fi reconciliată cu factura '+document.name)
                available = sum((abs(number(l.amount_residual)) for l in payment_lines),Decimal(0))
                if remaining > available:
                    raise UserError('Supraplata nu există pe nota de plată '+str(link['ID_NOTA']))
                unmatched_overpayments.append({'source_document':docid,'amount':str(remaining)})
        for docid,(document,invoice,row,counter) in native_docs.items():
            invoice.invalidate_recordset(['amount_residual','payment_state'])
            expected = max(number(row['NEACHITAT']),Decimal(0))
            if number(str(invoice.amount_residual)).quantize(Decimal('.01')) != expected:
                raise UserError('Sold necorelat după import: '+document.name)

        # Historical fixed-asset register: no new depreciation entries are generated.
        for row in data.get('PVR',[]):
            env['saga.asset.history'].create({'batch_id':self.id,'company_id':company.id,'name':clean(row['DENUMIRE']),
                'inventory_number':clean(row.get('NRINV')),'acquisition_date':date(row.get('DATA')),
                'purchase_value':float(number(row.get('VAL'))),'remaining_value':float(number(row.get('VALRAM'))),
                'monthly_depreciation':float(number(row.get('AMORTLUNA'))),'account_code':clean(row.get('CONT')),
                'depreciation_account':clean(row.get('CONT_AM')),'source_id':row['ID']})
        employees = []
        for row in data.get('SALARIATI',[]):
            employee = env['hr.employee'].create({'name':clean(row.get('NUME'))+' '+clean(row.get('PRENUME')),
                'company_id':company.id,'job_title':clean(row.get('FUNCTIE')),'work_email':clean(row.get('EMAIL')) or False})
            employees.append(employee.id)
        for row in data.get('STATE',[]):
            env['saga.payroll.history'].create({'batch_id':self.id,'company_id':company.id,'name':str(row['an'])+'-'+str(row['LUNA']).zfill(2),
                'year':row['an'],'month':row['LUNA'],'payment_date':date(row.get('DATA_PLATA')),
                'gross_total':float(number(row.get('CHELT_SAL'))),'income_tax':float(number(row.get('IMPOZIT'))),
                'cas':float(number(row.get('PENSIE'))),'cass':float(number(row.get('SANATATE_A'))),
                'source_id':row['ID'],'details_available':bool(data.get('SS'))})
        sensitive = {'PAROLA','PASSWORD','TOKEN','P_F','KEY','PPO','MID','U_WS'}
        archive_vals = []
        for table, rows in data.items():
            for index,row in enumerate(rows,1):
                sanitized = {k:('[REDACTAT]' if k.upper() in sensitive and v else v) for k,v in row.items()}
                archive_vals.append({'batch_id':self.id,'company_id':company.id,'table_name':table,'source_row':index,
                                     'payload':json.dumps(sanitized,ensure_ascii=False)})
        for start in range(0,len(archive_vals),500):
            env['saga.source.row'].create(archive_vals[start:start+500])
        # Independent verification: compare every account/year's signed debit and
        # credit, not merely a grand total (which would hide duplicated postings).
        env.flush_all()
        expected = defaultdict(lambda:[Decimal(0),Decimal(0)])
        for key,lines in normalized.items():
            for line in lines:
                expected[(key[2][:4],line['account'])][0 if line['side']=='debit' else 1] += line['amount']
        actual = defaultdict(lambda:[Decimal(0),Decimal(0)])
        all_moves = env['account.move'].search([('saga_batch_id','=',self.id)])
        for line in all_moves.line_ids:
            actual[(str(line.date.year),line.account_id.code)][0] += number(line.debit)
            actual[(str(line.date.year),line.account_id.code)][1] += number(line.credit)
        mismatches = []
        for key in set(expected)|set(actual):
            if [v.quantize(Decimal('.01')) for v in expected[key]] != [v.quantize(Decimal('.01')) for v in actual[key]]:
                mismatches.append(str(key)+': '+str(expected[key])+' / '+str(actual[key]))
        if mismatches:
            raise UserError('Registrul importat diferă de SAGA: '+'; '.join(mismatches[:8]))
        company.partner_id.comment = 'Import SAGA. EUID: '+clean(self.euid)+'; backup SHA256: '+self.source_hash
        # Preserve source fiscal close as information; applying a lock requires review.
        result = {**check,'company_id':company.id,'company_name':company.name,'posted_moves':len(all_moves),
            'native_invoices_created':len(native_docs),'historical_documents_created':len(docs)-len(native_docs),
            'source_records_preserved':len(archive_vals),'assets_history':len(data.get('PVR',[])),
            'payroll_periods_history':len(data.get('STATE',[])),'employees':len(employees),
            'verified_account_year_pairs':len(expected),'signed_debit_credit_match':True,'native_invoice_residuals_match':True,
            'overpayments_preserved_on_payment':unmatched_overpayments,'source_last_close':date(data['SOCIET'][0].get('DATA_INCH'))}
        self._prepare_operations()
        return result


class AccountMove(models.Model):
    _inherit = 'account.move'
    saga_batch_id = fields.Many2one('saga.import.batch',string='Import SAGA',copy=False,index=True,readonly=True)


class SagaDocument(models.Model):
    _name = 'saga.document'
    _description = 'Document importat din SAGA'
    _order = 'date desc, id desc'
    name = fields.Char(string='Număr document',required=True)
    batch_id = fields.Many2one('saga.import.batch',required=True,ondelete='restrict')
    company_id = fields.Many2one('res.company',required=True,index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    kind = fields.Selection([('purchase','Intrare'),('sale','Ieșire')],required=True,string='Tip')
    source_id = fields.Integer(string='ID SAGA')
    date = fields.Date(string='Data')
    due_date = fields.Date(string='Scadență')
    partner_id = fields.Many2one('res.partner',string='Partener')
    amount_total = fields.Monetary(string='Total')
    source_residual = fields.Monetary(string='Sold SAGA')
    source_counterpart = fields.Char(string='Cont contraparte SAGA')
    handling = fields.Selection([('native','Factură Odoo'),('historical','Document istoric + notă contabilă')],string='Preluare')
    move_id = fields.Many2one('account.move',string='Înregistrare Odoo')
    line_ids = fields.One2many('saga.document.line','document_id',string='Linii')
    _unique_source = models.Constraint('UNIQUE(batch_id,kind,source_id)','Document SAGA duplicat.')


class SagaDocumentLine(models.Model):
    _name = 'saga.document.line'
    _description = 'Linie document SAGA'
    document_id = fields.Many2one('saga.document',required=True,ondelete='cascade')
    company_id = fields.Many2one(related='document_id.company_id',store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    name = fields.Char(string='Descriere')
    quantity = fields.Float(string='Cantitate',digits=(16,6))
    price_unit = fields.Float(string='Preț',digits=(16,6))
    amount_total = fields.Monetary(string='Total')
    source_account = fields.Char(string='Cont din document')


class SagaAssetHistory(models.Model):
    _name = 'saga.asset.history'
    _description = 'Registru istoric imobilizări SAGA'
    name = fields.Char(string='Denumire')
    batch_id = fields.Many2one('saga.import.batch',required=True,ondelete='restrict')
    company_id = fields.Many2one('res.company',required=True,index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    source_id = fields.Integer(string='ID SAGA')
    inventory_number = fields.Char(string='Nr. inventar')
    acquisition_date = fields.Date(string='Data achiziției')
    purchase_value = fields.Monetary(string='Valoare SAGA (VAL)')
    remaining_value = fields.Monetary(string='Valoare rămasă SAGA (VALRAM)')
    monthly_depreciation = fields.Monetary(string='Amortizare lunară SAGA')
    account_code = fields.Char(string='Cont imobilizare')
    depreciation_account = fields.Char(string='Cont amortizare')


class SagaPayrollHistory(models.Model):
    _name = 'saga.payroll.history'
    _description = 'Istoric state salariale SAGA'
    name = fields.Char(string='Perioadă')
    batch_id = fields.Many2one('saga.import.batch',required=True,ondelete='restrict')
    company_id = fields.Many2one('res.company',required=True,index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    source_id = fields.Integer(string='ID SAGA')
    year = fields.Integer(string='An')
    month = fields.Integer(string='Lună')
    payment_date = fields.Date(string='Data plății din SAGA')
    gross_total = fields.Monetary(string='Cheltuieli salariale SAGA')
    income_tax = fields.Monetary(string='Impozit SAGA')
    cas = fields.Monetary(string='PENSIE din SAGA')
    cass = fields.Monetary(string='SANATATE_A din SAGA')
    details_available = fields.Boolean(string='Detalii individuale disponibile')


class SagaSourceRow(models.Model):
    _name = 'saga.source.row'
    _description = 'Arhivă sursă SAGA (administratori)'
    _rec_name = 'table_name'
    _order = 'table_name, source_row'
    batch_id = fields.Many2one('saga.import.batch',required=True,ondelete='restrict',index=True)
    company_id = fields.Many2one('res.company',required=True,index=True)
    table_name = fields.Char(string='Tabel',required=True,index=True)
    source_row = fields.Integer(string='Rând')
    payload = fields.Text(string='Date originale (secretele tehnice mascate)')

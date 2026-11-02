import calendar
import json
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


def money(value, digits='0.01'):
    return float(Decimal(str(value)).quantize(Decimal(digits), rounding=ROUND_HALF_UP))


def entry_line(account, amount, label, partner=False):
    return (0, 0, {'account_id': account.id, 'name': label,
                   'partner_id': partner.id if partner else False,
                   'debit': max(money(amount), 0), 'credit': max(money(-amount), 0)})


def open_record(model, record_id):
    return {'type': 'ir.actions.act_window', 'res_model': model,
            'res_id': record_id, 'view_mode': 'form', 'target': 'current'}


def demo_only(record):
    if record.env.cr.dbname != 'greentech_financiar_test':
        raise UserError('Acest modul este pentru baza demonstrativă. Nu este un motor de salarizare fiscală certificat.')


class Employee(models.Model):
    _inherit = 'hr.employee'
    gt_payroll_demo = fields.Boolean('Angajat fictiv pentru salarizare', groups='hr.group_hr_manager')
    gt_payroll_partner_id = fields.Many2one('res.partner', 'Partener contabil salariat', groups='hr.group_hr_manager', check_company=True)


class LeaveType(models.Model):
    _inherit = 'hr.leave.type'
    gt_payroll_kind = fields.Selection([
        ('unsupported','Necesită analiză separată'),('paid','Concediu odihnă'),
        ('unpaid','Concediu fără plată'),('medical','Concediu medical'),
    ], default='unsupported', string='Tratament în salarizarea DEMO')


class Policy(models.Model):
    _name = 'gt.payroll.policy'
    _description = 'Parametri salarizare DEMO'
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s:s.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    cas_rate = fields.Float('CAS %', default=25, required=True)
    cass_rate = fields.Float('CASS %', default=10, required=True)
    tax_rate = fields.Float('Impozit %', default=10, required=True)
    cam_rate = fields.Float('CAM %', default=2.25, required=True)
    minimum_supported_gross = fields.Monetary('Brut minim al scenariului simplificat', default=8000, required=True)
    payroll_journal_id = fields.Many2one('account.journal', 'Jurnal salarii', required=True, check_company=True)
    travel_journal_id = fields.Many2one('account.journal', 'Jurnal delegații', required=True, check_company=True)
    bank_journal_id = fields.Many2one('account.journal', 'Jurnal bancă simulată', required=True, check_company=True)
    salary_expense_id = fields.Many2one('account.account', '641 - salarii', required=True, check_company=True)
    salary_payable_id = fields.Many2one('account.account', '421 - salarii de plată', required=True, check_company=True)
    cas_account_id = fields.Many2one('account.account', '4315 - CAS', required=True, check_company=True)
    cass_account_id = fields.Many2one('account.account', '4316 - CASS', required=True, check_company=True)
    tax_account_id = fields.Many2one('account.account', '444 - impozit', required=True, check_company=True)
    cam_account_id = fields.Many2one('account.account', '436 - CAM', required=True, check_company=True)
    cam_expense_id = fields.Many2one('account.account', '646 - cheltuială CAM', required=True, check_company=True)
    travel_expense_id = fields.Many2one('account.account', '625 - deplasări', required=True, check_company=True)
    advance_account_id = fields.Many2one('account.account', '542 - avansuri', required=True, check_company=True)
    travel_payable_id = fields.Many2one('account.account', '4281 - deconturi de plată', required=True, check_company=True)
    notes = fields.Text(default='DEMO: normă întreagă, condiții normale, fără facilități, tichete sau concedii medicale. Deducerile și indemnizația CO se verifică separat. Exportul de pregătire nu este declarație D112.')

    @api.constrains('date_from','date_to','cas_rate','cass_rate','tax_rate','cam_rate','minimum_supported_gross')
    def _check_values(self):
        for r in self:
            if r.date_from > r.date_to or r.minimum_supported_gross <= 0 or any(not 0 <= x <= 100 for x in [r.cas_rate,r.cass_rate,r.tax_rate,r.cam_rate]):
                raise ValidationError('Perioada și procentele parametrilor nu sunt valide.')

    def write(self, vals):
        if self.env['gt.payroll.slip'].search_count([('period_id.policy_id','in',self.ids),('state','in',['posted','paid'])]):
            raise UserError('Parametrii au fost utilizați în state contabilizate. Creați un set nou pentru altă perioadă.')
        return super().write(vals)


class Trip(models.Model):
    _name = 'gt.payroll.trip'
    _description = 'Delegație și decont DEMO'
    _order = 'departure desc, id desc'
    _check_company_auto = True
    name = fields.Char('Referință', required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s:s.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    employee_id = fields.Many2one('hr.employee', 'Angajat', required=True, check_company=True)
    policy_id = fields.Many2one('gt.payroll.policy', 'Parametri', required=True, check_company=True)
    kind = fields.Selection([('domestic','Internă'),('foreign','Externă')], default='domestic', required=True, string='Tip')
    country_id = fields.Many2one('res.country', 'Țară', required=True)
    destination = fields.Char('Destinație', required=True)
    purpose = fields.Char('Scop', required=True)
    departure = fields.Datetime('Plecare / trecere frontieră', required=True)
    arrival = fields.Datetime('Sosire / revenire frontieră', required=True)
    allowance_currency_id = fields.Many2one('res.currency', 'Monedă diurnă', required=True)
    rate = fields.Float('Diurnă acordată / zi', required=True, digits=(16,2))
    reference_rate = fields.Float('Referință publică / zi, verificată', required=True, digits=(16,2))
    fx_rate = fields.Float('RON pentru 1 unitate valută', default=1, required=True, digits=(16,6))
    exchange_date = fields.Date('Data cursului', required=True)
    exchange_source = fields.Char('Sursa cursului / regulii', required=True)
    basic_wage = fields.Monetary('Salariul de bază pentru plafon', required=True)
    working_days = fields.Integer('Zile lucrătoare în luna deplasării', required=True, default=22)
    payroll_date = fields.Date('Luna fiscală verificată - dată', required=True)
    settlement_date = fields.Date('Data decontului / plății', required=True)
    advance_date = fields.Date('Data avansului')
    advance_amount = fields.Monetary('Avans RON')
    transport_amount = fields.Monetary('Transport justificat RON')
    lodging_amount = fields.Monetary('Cazare justificată RON')
    receipt_note = fields.Text('Documente justificative')
    reviewed = fields.Boolean('Perioadă, curs, plafoane și documente verificate')
    hours = fields.Float('Durată ore', compute='_compute_amounts', store=True)
    days = fields.Float('Zile diurnă', compute='_compute_amounts', store=True)
    allowance = fields.Monetary('Diurnă totală RON', compute='_compute_amounts', store=True)
    exempt_amount = fields.Monetary('Diurnă neimpozabilă RON', compute='_compute_amounts', store=True)
    taxable_amount = fields.Monetary('Diurnă impozabilă RON', compute='_compute_amounts', store=True)
    total_amount = fields.Monetary('Total decont RON', compute='_compute_amounts', store=True)
    remaining_amount = fields.Monetary('De plată / de restituit', compute='_compute_amounts', store=True)
    state = fields.Selection([('draft','Ciornă'),('approved','Aprobat'),('settled','Decontat')], default='draft', readonly=True, copy=False)
    advance_move_id = fields.Many2one('account.move', 'Nota avans', readonly=True, copy=False)
    expense_move_id = fields.Many2one('account.move', 'Nota decont', readonly=True, copy=False)
    settlement_move_id = fields.Many2one('account.move', 'Nota plată / restituire', readonly=True, copy=False)

    @api.depends('departure','arrival','kind','rate','reference_rate','fx_rate','basic_wage','working_days','advance_amount','transport_amount','lodging_amount')
    def _compute_amounts(self):
        for r in self:
            hours=max(0,(r.arrival-r.departure).total_seconds()/3600) if r.departure and r.arrival else 0
            full=int(hours//24); rest=round(hours-full*24,8)
            extra=(1 if rest>=12 else 0) if r.kind=='domestic' else (0 if rest==0 else .5 if rest<=12 else 1)
            r.hours=hours; r.days=full+extra
            r.allowance=money(r.days*r.rate*r.fx_rate)
            daily_limit=2.5*r.reference_rate*r.fx_rate*r.days
            salary_limit=3*r.basic_wage/r.working_days*r.days if r.working_days else 0
            r.exempt_amount=money(min(r.allowance,daily_limit,salary_limit))
            r.taxable_amount=money(r.allowance-r.exempt_amount)
            r.total_amount=money(r.allowance+r.transport_amount+r.lodging_amount)
            r.remaining_amount=money(r.total_amount-r.advance_amount)

    @api.constrains('departure','arrival','rate','reference_rate','fx_rate','working_days','advance_amount','transport_amount','lodging_amount','basic_wage')
    def _check_values(self):
        for r in self:
            if r.departure and r.arrival and r.arrival<=r.departure:
                raise ValidationError('Sosirea trebuie să fie după plecare.')
            if any(x<0 for x in [r.rate,r.reference_rate,r.advance_amount,r.transport_amount,r.lodging_amount]) or r.fx_rate<=0 or r.working_days<=0 or r.basic_wage<=0:
                raise ValidationError('Sumele și zilele de lucru trebuie să fie valide și nenegative.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state','draft')!='draft' or any(vals.get(k) for k in ['advance_move_id','expense_move_id','settlement_move_id']):
                raise UserError('Delegația se creează în ciornă, fără note contabile asociate manual.')
        return super().create(vals_list)

    def write(self, vals):
        if any(k in vals for k in ['state','advance_move_id','expense_move_id','settlement_move_id']) or any(r.state!='draft' or r.advance_move_id for r in self):
            raise UserError('Delegația aprobată sau cu avans înregistrat nu se modifică direct.')
        return super().write(vals)

    def unlink(self):
        if any(r.state!='draft' or r.advance_move_id for r in self):
            raise UserError('Delegațiile contabilizate se păstrează pentru trasabilitate.')
        return super().unlink()

    def _lock(self):
        self.ensure_one(); demo_only(self)
        self.env.cr.execute('SELECT id FROM gt_payroll_trip WHERE id=%s FOR UPDATE',[self.id])
        self.invalidate_recordset()

    def _partner(self):
        partner=self.employee_id.gt_payroll_partner_id
        if not self.employee_id.gt_payroll_demo or not partner:
            raise UserError('Selectați un angajat DEMO cu partener contabil configurat.')
        return partner

    def _validate_trip(self):
        self.ensure_one(); self._partner()
        if not self.reviewed:
            raise UserError('Verificați și bifați perioada, cursul, plafoanele și documentele.')
        departure=fields.Datetime.context_timestamp(self,self.departure)
        arrival=fields.Datetime.context_timestamp(self,self.arrival)
        if (departure.year,departure.month)!=(arrival.year,arrival.month):
            raise UserError('Pentru exemplul DEMO, împărțiți deplasările la limita lunilor și țărilor.')
        if not self.policy_id.date_from<=self.payroll_date<=self.policy_id.date_to:
            raise UserError('Luna fiscală nu este acoperită de setul de parametri.')
        if self.search_count([('id','!=',self.id),('employee_id','=',self.employee_id.id),('state','!=','draft'),('departure','<',self.arrival),('arrival','>',self.departure)]):
            raise UserError('Există deja o delegație aprobată care se suprapune.')
        if self.env['gt.payroll.slip'].search_count([('employee_id','=',self.employee_id.id),('state','in',['posted','paid']),('period_id.date_from','<=',self.payroll_date),('period_id.date_to','>=',self.payroll_date)]):
            raise UserError('Statul acestei luni este contabilizat. Nu adăugați diurne după închiderea salarizării.')
        if self.currency_id!=self.allowance_currency_id and not self.exchange_source:
            raise UserError('Documentați cursul valutar.')
        if self.currency_id==self.allowance_currency_id and self.fx_rate!=1:
            raise UserError('Pentru RON, cursul trebuie să fie 1.')

    def action_advance(self):
        self._lock(); self._validate_trip()
        if self.state!='draft' or self.advance_move_id or self.advance_amount<=0 or not self.advance_date:
            raise UserError('Avansul necesită o ciornă, dată și sumă pozitivă; nu se înregistrează de două ori.')
        p=self.policy_id; partner=self._partner()
        move=self.env['account.move'].create({'move_type':'entry','company_id':self.company_id.id,'journal_id':p.bank_journal_id.id,'date':self.advance_date,'ref':self.name+' / avans DEMO','line_ids':[
            entry_line(p.advance_account_id,self.advance_amount,self.name,partner),
            entry_line(p.bank_journal_id.default_account_id,-self.advance_amount,self.name,partner)]})
        move.action_post(); super(Trip,self).write({'advance_move_id':move.id})
        return open_record('account.move',move.id)

    def action_approve(self):
        self._lock(); self._validate_trip()
        if self.state!='draft' or self.expense_move_id:
            raise UserError('Delegația este deja aprobată.')
        if self.advance_amount and not self.advance_move_id:
            raise UserError('Înregistrați mai întâi avansul sau corectați suma avansului.')
        if self.advance_move_id and self.advance_move_id.state!='posted':
            raise UserError('Nota avansului nu mai este validată. Verificați contabilitatea înainte de decont.')
        if self.total_amount<=0:
            raise UserError('Decontul nu are sume pozitive.')
        p=self.policy_id; partner=self._partner()
        move=self.env['account.move'].create({'move_type':'entry','company_id':self.company_id.id,'journal_id':p.travel_journal_id.id,'date':self.settlement_date,'ref':self.name+' / decont DEMO','line_ids':[
            entry_line(p.travel_expense_id,self.total_amount,self.name,partner),
            entry_line(p.travel_payable_id,-self.total_amount,self.name,partner)]})
        move.action_post(); super(Trip,self).write({'state':'approved','expense_move_id':move.id})
        return open_record(self._name,self.id)

    def action_settle(self):
        self._lock()
        if self.state!='approved' or self.settlement_move_id:
            raise UserError('Aprobați decontul; plata nu se înregistrează de două ori.')
        if self.expense_move_id.state!='posted':
            raise UserError('Nota decontului nu mai este validată.')
        p=self.policy_id; partner=self._partner()
        lines=[entry_line(p.travel_payable_id,self.total_amount,self.name,partner)]
        if self.advance_amount:
            lines.append(entry_line(p.advance_account_id,-self.advance_amount,self.name,partner))
        if self.remaining_amount:
            lines.append(entry_line(p.bank_journal_id.default_account_id,-self.remaining_amount,self.name,partner))
        move=self.env['account.move'].create({'move_type':'entry','company_id':self.company_id.id,'journal_id':p.bank_journal_id.id,'date':self.settlement_date,'ref':self.name+' / plată simulată','line_ids':lines})
        move.action_post()
        for account, source in [(p.advance_account_id,self.advance_move_id),(p.travel_payable_id,self.expense_move_id)]:
            if source and account.reconcile:
                (source.line_ids+move.line_ids).filtered(lambda l:l.account_id==account and not l.reconciled).reconcile()
        super(Trip,self).write({'state':'settled','settlement_move_id':move.id})
        return open_record('account.move',move.id)

    def action_print(self):
        return self.env.ref('greentech_hr_payroll_demo.report_trip').report_action(self)


class Period(models.Model):
    _name = 'gt.payroll.period'
    _description = 'Stat de salarii DEMO'
    _order = 'date_from desc'
    _check_company_auto = True
    name = fields.Char('Denumire', required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s:s.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date_from = fields.Date('Prima zi a lunii', required=True)
    date_to = fields.Date('Ultima zi a lunii', compute='_compute_dates', store=True)
    scheduled_days = fields.Integer('Zile lucrătoare verificate', required=True)
    policy_id = fields.Many2one('gt.payroll.policy', 'Parametri', required=True, check_company=True)
    payment_date = fields.Date('Data plății simulate', required=True)
    slip_ids = fields.One2many('gt.payroll.slip','period_id','Salariați')
    state = fields.Selection([('draft','În lucru'),('calculated','Calculat'),('posted','Contabilizat'),('paid','Achitat')],compute='_compute_totals',store=True)
    total_gross = fields.Monetary('Brut fiscal',compute='_compute_totals',store=True)
    total_net = fields.Monetary('Net de plată',compute='_compute_totals',store=True)
    total_tax = fields.Monetary('CAS + CASS + impozit + CAM',compute='_compute_totals',store=True)
    total_cost = fields.Monetary('Cost salarial fără deconturi',compute='_compute_totals',store=True)
    d112_status = fields.Char('Stare D112', default='Pregătire DEMO — nu este declarație validată', readonly=True)
    d112_check = fields.Text('Verificări D112',readonly=True)
    notes = fields.Text('Observații')
    _unique_period = models.Constraint('UNIQUE(company_id, date_from)','Există deja un stat pentru această companie și lună.')

    @api.depends('date_from')
    def _compute_dates(self):
        for r in self:
            r.date_to=fields.Date.end_of(r.date_from,'month') if r.date_from else False

    @api.depends('slip_ids.state','slip_ids.taxable_gross','slip_ids.net_pay','slip_ids.cas','slip_ids.cass','slip_ids.income_tax','slip_ids.cam','slip_ids.employer_cost')
    def _compute_totals(self):
        for r in self:
            r.total_gross=sum(r.slip_ids.mapped('taxable_gross'));r.total_net=sum(r.slip_ids.mapped('net_pay'))
            r.total_tax=sum(x.cas+x.cass+x.income_tax+x.cam for x in r.slip_ids)
            r.total_cost=sum(r.slip_ids.mapped('employer_cost'))
            states=set(r.slip_ids.mapped('state'))
            r.state='paid' if states=={'paid'} else 'posted' if states and states<={'posted','paid'} else 'calculated' if states and 'draft' not in states else 'draft'

    @api.constrains('date_from','date_to','scheduled_days','policy_id','payment_date')
    def _check_dates(self):
        for r in self:
            if r.date_from.day!=1 or not 1<=r.scheduled_days<=31:
                raise ValidationError('Alegeți prima zi a lunii și numărul verificat de zile lucrătoare.')
            if not r.policy_id.date_from<=r.date_from<=r.date_to<=r.policy_id.date_to:
                raise ValidationError('Setul de parametri nu acoperă întreaga lună.')
            if r.payment_date<r.date_to:
                raise ValidationError('Plata statului DEMO se face la sau după sfârșitul lunii.')

    def write(self,vals):
        if any(r.slip_ids.filtered(lambda s:s.state in ('posted','paid')) for r in self) and set(vals)-{'notes'}:
            raise UserError('Perioada cu salarii contabilizate nu se modifică.')
        return super().write(vals)

    def action_generate(self):
        self.ensure_one();demo_only(self)
        employees=self.env['hr.employee'].search([('company_id','=',self.company_id.id),('gt_payroll_demo','=',True),('active','=',True)])
        if not employees:
            raise UserError('Nu există angajați DEMO configurați.')
        for employee in employees-self.slip_ids.employee_id:
            versions=self.env['hr.version'].search([('employee_id','=',employee.id),('date_version','<=',self.date_from)],order='date_version desc',limit=1)
            if not versions or not versions.contract_date_start or versions.contract_date_start>self.date_from or (versions.contract_date_end and versions.contract_date_end<self.date_to):
                raise UserError('Contractul trebuie să acopere luna întreagă pentru %s.'%employee.name)
            self.env['gt.payroll.slip'].create({'period_id':self.id,'employee_id':employee.id,'version_id':versions.id,'basic_wage':versions.wage,'worked_days':self.scheduled_days})
        return open_record(self._name,self.id)

    def action_compute(self):
        self.ensure_one()
        if not self.slip_ids:raise UserError('Adăugați salariații în stat.')
        for slip in self.slip_ids.filtered(lambda x:x.state in ('draft','calculated')):slip.action_compute()
        return open_record(self._name,self.id)

    def action_post(self):
        self.ensure_one()
        if not self.slip_ids:raise UserError('Statul este gol.')
        for slip in self.slip_ids.filtered(lambda x:x.state not in ('posted','paid')):slip.action_post()
        return open_record(self._name,self.id)

    def action_pay(self):
        self.ensure_one()
        if not self.slip_ids or any(x.state not in ('posted','paid') for x in self.slip_ids):raise UserError('Contabilizați întregul stat înainte de plată.')
        for slip in self.slip_ids.filtered(lambda x:x.state=='posted'):slip.action_pay()
        return open_record(self._name,self.id)

    def action_print(self):
        return self.env.ref('greentech_hr_payroll_demo.report_payroll').report_action(self)

    def action_xlsx(self):
        return self.env.ref('greentech_hr_payroll_demo.report_payroll_xlsx').report_action(self)

    def action_check_d112(self):
        self.ensure_one()
        problems=['Generatorul XML D112 și validarea ANAF nu sunt instalate. Acest export este o centralizare, nu declarația D112.',
                  'Firma și salariații folosesc date fictive; nu se depun la ANAF.',
                  'Regimul DEMO exclude salariul minim/facilitățile, timp parțial, tichetele, concediile medicale și cazurile speciale.',
                  'Schema/validatorul oficial trebuie selectate pentru luna declarată: https://static.anaf.ro/static/10/Anaf/Declaratii_R/112.html']
        if any(x.state in ('draft','calculated') for x in self.slip_ids) or not self.slip_ids:problems.append('Statul nu este integral contabilizat.')
        if not self.company_id.vat:problems.append('Lipsește CUI-ul real al angajatorului.')
        for slip in self.slip_ids:
            if not slip.employee_id.identification_id:problems.append('%s: lipsă CNP/NIF real.'%slip.employee_id.name)
        super(Period,self).write({'d112_check':'\n'.join('• '+p for p in problems)})
        return open_record(self._name,self.id)


class Slip(models.Model):
    _name = 'gt.payroll.slip'
    _description = 'Fluturaș și pontaj lunar DEMO'
    _rec_name = 'employee_id'
    _check_company_auto = True
    period_id = fields.Many2one('gt.payroll.period','Stat lunar',required=True,ondelete='restrict',check_company=True)
    company_id = fields.Many2one(related='period_id.company_id',store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    employee_id = fields.Many2one('hr.employee','Angajat',required=True,check_company=True)
    version_id = fields.Many2one('hr.version','Versiune contract',required=True,check_company=True)
    basic_wage = fields.Monetary('Salariu brut contract',required=True)
    worked_days = fields.Float('Zile lucrate',required=True)
    paid_leave_days = fields.Float('Zile concediu odihnă')
    unpaid_days = fields.Float('Zile fără plată / absențe')
    medical_days = fields.Float('Zile concediu medical (nesuportat DEMO)')
    leave_daily_rate = fields.Monetary('Indemnizație CO / zi verificată')
    overtime_hours = fields.Float('Ore suplimentare de plată')
    overtime_percent = fields.Float('Spor ore suplimentare %',default=75)
    bonus = fields.Monetary('Prime / sporuri brute')
    personal_deduction = fields.Monetary('Deducere personală verificată')
    other_deduction = fields.Monetary('Alte deduceri fiscale verificate')
    reviewed = fields.Boolean('Pontajul și deducerile au fost verificate')
    notes = fields.Text('Observații pontaj și calcul')
    trip_ids = fields.Many2many('gt.payroll.trip',string='Diurne incluse în calcul',readonly=True,copy=False)
    cash_gross = fields.Monetary('Brut salarial',readonly=True,copy=False)
    trip_taxable = fields.Monetary('Diurne impozabile deja decontate',readonly=True,copy=False)
    trip_exempt = fields.Monetary('Diurne neimpozabile',readonly=True,copy=False)
    taxable_gross = fields.Monetary('Brut fiscal / bază contribuții',readonly=True,copy=False)
    cas = fields.Monetary('CAS',readonly=True,copy=False)
    cass = fields.Monetary('CASS',readonly=True,copy=False)
    tax_base = fields.Monetary('Bază impozit',readonly=True,copy=False)
    income_tax = fields.Monetary('Impozit',readonly=True,copy=False)
    cam = fields.Monetary('CAM angajator',readonly=True,copy=False)
    net_pay = fields.Monetary('Net salariu de plată',readonly=True,copy=False)
    employer_cost = fields.Monetary('Cost salarial fără deconturi',readonly=True,copy=False)
    calculation_note = fields.Text('Detalii calcul și parametri utilizați',readonly=True,copy=False)
    state = fields.Selection([('draft','Ciornă'),('calculated','Calculat'),('posted','Contabilizat'),('paid','Achitat')],default='draft',readonly=True,copy=False)
    move_id = fields.Many2one('account.move','Nota salarii',readonly=True,copy=False)
    payment_move_id = fields.Many2one('account.move','Plata simulată',readonly=True,copy=False)
    _unique_slip = models.Constraint('UNIQUE(period_id,employee_id)','Angajatul există deja în acest stat.')

    def _protected(self):
        return {'state','move_id','payment_move_id','trip_ids','cash_gross','trip_taxable','trip_exempt','taxable_gross','cas','cass','tax_base','income_tax','cam','net_pay','employer_cost','calculation_note'}

    @api.model_create_multi
    def create(self,vals_list):
        for vals in vals_list:
            if self._protected().intersection(vals):raise UserError('Creați fluturașul în ciornă și folosiți Calculare.')
        return super().create(vals_list)

    def write(self,vals):
        if self._protected().intersection(vals) or any(r.state in ('posted','paid') for r in self):
            raise UserError('Rezultatele și statele contabilizate nu se modifică direct.')
        result=super().write(vals)
        super(Slip,self).write({'state':'draft'})
        return result

    def unlink(self):
        if any(r.state in ('posted','paid') for r in self):raise UserError('Fluturașii contabilizați nu se șterg.')
        return super().unlink()

    def _lock(self):
        self.ensure_one();demo_only(self)
        self.env.cr.execute('SELECT id FROM gt_payroll_slip WHERE id=%s FOR UPDATE',[self.id])
        self.invalidate_recordset()

    def action_sync_leave(self):
        self.ensure_one()
        if self.state not in ('draft','calculated'):raise UserError('Statul este deja contabilizat.')
        leaves=self.env['hr.leave'].search([('employee_id','=',self.employee_id.id),('state','=','validate'),('request_date_from','<=',self.period_id.date_to),('request_date_to','>=',self.period_id.date_from)])
        if any(l.request_date_from<self.period_id.date_from or l.request_date_to>self.period_id.date_to for l in leaves):
            raise UserError('Concediul traversează luna; repartizați zilele manual și verificați pontajul.')
        if leaves.filtered(lambda l:l.holiday_status_id.gt_payroll_kind=='unsupported'):
            raise UserError('Un tip de concediu nu are tratamentul salarial configurat. Nu îl putem considera automat concediu de odihnă.')
        paid=sum(l.number_of_days for l in leaves if l.holiday_status_id.gt_payroll_kind=='paid')
        unpaid=sum(l.number_of_days for l in leaves if l.holiday_status_id.gt_payroll_kind=='unpaid')
        medical=sum(l.number_of_days for l in leaves if l.holiday_status_id.gt_payroll_kind=='medical')
        self.write({'paid_leave_days':paid,'unpaid_days':unpaid,'medical_days':medical,'worked_days':self.period_id.scheduled_days-paid-unpaid-medical,'reviewed':False})
        return open_record(self._name,self.id)

    def action_compute(self):
        self._lock()
        if self.state not in ('draft','calculated'):raise UserError('Salariul este contabilizat; nu se recalculează direct.')
        if not self.employee_id.gt_payroll_demo or not self.employee_id.gt_payroll_partner_id:raise UserError('Este necesar un angajat fictiv cu partener contabil.')
        if self.version_id.employee_id!=self.employee_id:raise UserError('Contractul nu aparține angajatului.')
        if not self.reviewed:raise UserError('Verificați pontajul, indemnizația CO și deducerile, apoi bifați confirmarea.')
        if self.medical_days:raise UserError('Concediul medical necesită un motor de salarizare românească validat; calculul DEMO este oprit.')
        if self.version_id.resource_calendar_id.hours_per_day!=8 or self.version_id.resource_calendar_id.hours_per_week!=40:raise UserError('Scenariul DEMO suportă numai normă întreagă de 8 ore / 40 ore săptămânal.')
        if not self.version_id.contract_date_start or self.version_id.contract_date_start>self.period_id.date_from or (self.version_id.contract_date_end and self.version_id.contract_date_end<self.period_id.date_to):
            raise UserError('Contractul nu acoperă luna întreagă. Exemplul DEMO nu proratează automat angajarea/încetarea în cursul lunii.')
        inputs=[self.worked_days,self.paid_leave_days,self.unpaid_days,self.leave_daily_rate,self.bonus,self.overtime_hours,self.personal_deduction,self.other_deduction]
        if any(x<0 for x in inputs) or abs(self.worked_days+self.paid_leave_days+self.unpaid_days-self.period_id.scheduled_days)>0.001:
            raise UserError('Zilele lucrate + CO + fără plată trebuie să egaleze zilele lunii; valorile nu pot fi negative.')
        if self.paid_leave_days and self.leave_daily_rate<=0:raise UserError('Introduceți indemnizația zilnică CO verificată; media legală nu se deduce automat dintr-un singur salariu.')
        p=self.period_id.policy_id; days=self.period_id.scheduled_days
        if self.overtime_hours and self.overtime_percent<75:raise UserError('Verificați sporul pentru ore suplimentare; exemplul de plată folosește minimum 75%.')
        trips=self.env['gt.payroll.trip'].search([('employee_id','=',self.employee_id.id),('payroll_date','>=',self.period_id.date_from),('payroll_date','<=',self.period_id.date_to)])
        if any(t.state!='settled' for t in trips):raise UserError('Finalizați decontarea diurnelor lunii înainte de calculul salariului.')
        gross=money(self.basic_wage/days*self.worked_days+self.leave_daily_rate*self.paid_leave_days+self.basic_wage/(days*8)*self.overtime_hours*(1+self.overtime_percent/100)+self.bonus)
        taxable=money(sum(trips.mapped('taxable_amount'))); exempt=money(sum(trips.mapped('exempt_amount')))
        base=money(gross+taxable)
        if gross<p.minimum_supported_gross:raise UserError('Brutul este sub limita scenariului simplificat. Sunt necesare verificări pentru salariul minim, deduceri și facilități într-un motor fiscal complet.')
        cas=money(base*p.cas_rate/100,'1');cass=money(base*p.cass_rate/100,'1')
        tax_base=money(max(0,base-cas-cass-self.personal_deduction-self.other_deduction))
        tax=money(tax_base*p.tax_rate/100,'1');cam=money(base*p.cam_rate/100,'1')
        net=money(gross-cas-cass-tax)
        if net<0:raise UserError('Reținerile depășesc salariul disponibil; verificați datele.')
        super(Slip,self).write({'cash_gross':gross,'trip_taxable':taxable,'trip_exempt':exempt,'taxable_gross':base,'cas':cas,'cass':cass,'tax_base':tax_base,'income_tax':tax,'cam':cam,'net_pay':net,'employer_cost':money(gross+cam),'trip_ids':[(6,0,trips.ids)],'state':'calculated',
            'calculation_note':json.dumps({'demo_only':True,'policy':p.name,'cas_rate':p.cas_rate,'cass_rate':p.cass_rate,'tax_rate':p.tax_rate,'cam_rate':p.cam_rate,'rounding':'contributii/impozit la leu, HALF_UP','trip_taxable_already_paid':taxable,'salary_gross':gross,'worked_days':self.worked_days,'paid_leave_days':self.paid_leave_days,'unpaid_days':self.unpaid_days,'leave_daily_rate':self.leave_daily_rate,'overtime_hours':self.overtime_hours,'personal_deduction':self.personal_deduction,'other_deduction':self.other_deduction},ensure_ascii=False,indent=2)})
        return open_record(self._name,self.id)

    def action_post(self):
        self._lock()
        if self.state not in ('draft','calculated') or self.move_id:raise UserError('Salariul a fost deja contabilizat.')
        self.action_compute();p=self.period_id.policy_id;partner=self.employee_id.gt_payroll_partner_id
        label=self.period_id.name+' / '+self.employee_id.name
        values=[(p.salary_expense_id,self.cash_gross),(p.cam_expense_id,self.cam),(p.salary_payable_id,-self.net_pay),(p.cas_account_id,-self.cas),(p.cass_account_id,-self.cass),(p.tax_account_id,-self.income_tax),(p.cam_account_id,-self.cam)]
        move=self.env['account.move'].create({'move_type':'entry','company_id':self.company_id.id,'journal_id':p.payroll_journal_id.id,'date':self.period_id.date_to,'ref':label,'line_ids':[entry_line(a,v,label,partner) for a,v in values if v]})
        move.action_post();super(Slip,self).write({'state':'posted','move_id':move.id})
        return open_record('account.move',move.id)

    def action_pay(self):
        self._lock()
        if self.state!='posted' or self.payment_move_id:raise UserError('Contabilizați salariul; plata nu se dublează.')
        if self.move_id.state!='posted':raise UserError('Nota salariului nu mai este validată. Verificați contabilitatea înainte de plată.')
        p=self.period_id.policy_id;partner=self.employee_id.gt_payroll_partner_id;label='Plată simulată / '+self.employee_id.name
        move=self.env['account.move'].create({'move_type':'entry','company_id':self.company_id.id,'journal_id':p.bank_journal_id.id,'date':self.period_id.payment_date,'ref':label,'line_ids':[entry_line(p.salary_payable_id,self.net_pay,label,partner),entry_line(p.bank_journal_id.default_account_id,-self.net_pay,label,partner)]})
        move.action_post()
        if p.salary_payable_id.reconcile:(self.move_id.line_ids+move.line_ids).filtered(lambda l:l.account_id==p.salary_payable_id and not l.reconciled).reconcile()
        super(Slip,self).write({'state':'paid','payment_move_id':move.id})
        return open_record('account.move',move.id)

    def action_print(self):
        return self.env.ref('greentech_hr_payroll_demo.report_slip').report_action(self)

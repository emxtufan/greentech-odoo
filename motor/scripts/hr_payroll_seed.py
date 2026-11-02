"""Install demo records into the existing 8070 database. No new server or launcher."""
import calendar
import json
from datetime import date
from financial_client import Client, ROOT

c=Client();s=c.state
group=c.ref('greentech_hr_payroll_demo.group_payroll_manager')
c.write('res.users',c.uid,{'group_ids':[(4,group)]})
c=Client();s=c.state
cron=c.call('ir.cron','search',[[]]);c.call('ir.cron','write',[cron,{'active':False}])

def account(prefix,reconcile=False):
    rows=c.search('account.account',[('code','=like',prefix+'%')],['code','reconcile'],limit=1)
    if not rows:raise RuntimeError('Missing account '+prefix)
    if reconcile and not rows[0]['reconcile']:c.write('account.account',rows[0]['id'],{'reconcile':True})
    return rows[0]['id']

journal=c.ensure('hr_salary_journal','account.journal',{'name':'Salarii DEMO','code':'SDMO','type':'general','company_id':1})
travel_journal=c.ensure('hr_travel_journal','account.journal',{'name':'Diurne DEMO','code':'DDMO','type':'general','company_id':1})
policy=c.ensure('hr_policy','gt.payroll.policy',{'name':'Regim standard DEMO / octombrie–decembrie 2026','company_id':1,'date_from':'2026-10-01','date_to':'2026-12-31',
    'payroll_journal_id':journal,'travel_journal_id':travel_journal,'bank_journal_id':s['bank_journal'],
    'salary_expense_id':account('641'),'salary_payable_id':account('421',True),'cas_account_id':account('4315'),
    'cass_account_id':account('4316'),'tax_account_id':account('444'),'cam_account_id':account('436'),'cam_expense_id':account('646'),
    'travel_expense_id':account('625'),'advance_account_id':account('542',True),'travel_payable_id':account('4281',True),
    'cas_rate':25,'cass_rate':10,'tax_rate':10,'cam_rate':2.25,'minimum_supported_gross':8000})

employees=[('Ion Popescu [DEMO]',11000,'Tehnician'),('Mara Ionescu [DEMO]',13200,'Coordonator tehnic'),('Radu Dumitrescu [DEMO]',8800,'Specialist suport')]
for i,(name,wage,job) in enumerate(employees):
    partner=c.ensure('hr_partner_'+str(i),'res.partner',{'name':name,'company_type':'person','company_id':1,'comment':'Persoană fictivă, fără CNP, email sau IBAN real.'})
    employee=c.ensure('hr_employee_'+str(i),'hr.employee',{'name':name,'company_id':1,'job_title':job,'country_id':c.ref('base.ro'),'gt_payroll_demo':True,'gt_payroll_partner_id':partner,
        'work_contact_id':partner,'wage':wage,'contract_date_start':'2026-01-01','date_version':'2026-01-01','tz':'Europe/Bucharest'})
    # Representative real attendance records; monthly payroll time remains a reviewed summary.
    for day in [1,2]:
        c.ensure(f'hr_attendance_{i}_{day}','hr.attendance',{'employee_id':employee,'check_in':f'2026-10-{day:02} 06:00:00','check_out':f'2026-10-{day:02} 14:00:00'})

leave_type=c.ensure('hr_paid_leave_type','hr.leave.type',{'name':'Concediu odihnă DEMO','gt_payroll_kind':'paid','requires_allocation':False,'leave_validation_type':'hr','company_id':1,'responsible_ids':[(6,0,[])]})
unpaid_type=c.ensure('hr_unpaid_leave_type','hr.leave.type',{'name':'Concediu fără plată DEMO','gt_payroll_kind':'unpaid','requires_allocation':False,'leave_validation_type':'hr','unpaid':True,'company_id':1,'responsible_ids':[(6,0,[])]})
c.write('hr.leave.type',leave_type,{'gt_payroll_kind':'paid'})
c.write('hr.leave.type',unpaid_type,{'gt_payroll_kind':'unpaid'})
for key,employee,typ,start,end in [('hr_leave_0',s['hr_employee_0'],leave_type,'2026-10-08','2026-10-09'),('hr_leave_2',s['hr_employee_2'],unpaid_type,'2026-10-19','2026-10-19')]:
    lid=c.ensure(key,'hr.leave',{'name':'Cerere fictivă pentru pontaj DEMO','employee_id':employee,'holiday_status_id':typ,'request_date_from':start,'request_date_to':end})
    status=c.read('hr.leave',lid,['state'])['state']
    if status not in ['validate']:
        c.call('hr.leave','action_approve',[[lid]])

workdays=sum(date(2026,10,d).weekday()<5 for d in range(1,32))
assert workdays==22
trips=[
    {'employee':0,'kind':'domestic','country':'base.ro','destination':'Brașov [DEMO]','departure':'2026-10-05 05:00:00','arrival':'2026-10-07 17:00:00','rate':75,'reference_rate':23,'currency':'base.RON','fx':1,'advance':500,'transport':150,'lodging':600,'settlement':'2026-10-08'},
    {'employee':1,'kind':'foreign','country':'base.de','destination':'Berlin [DEMO]','departure':'2026-10-12 05:00:00','arrival':'2026-10-15 17:00:00','rate':100,'reference_rate':35,'currency':'base.EUR','fx':5,'advance':2500,'transport':700,'lodging':1500,'settlement':'2026-10-16'},
    {'employee':2,'kind':'domestic','country':'base.ro','destination':'Ploiești [DEMO]','departure':'2026-10-06 05:00:00','arrival':'2026-10-07 05:00:00','rate':50,'reference_rate':23,'currency':'base.RON','fx':1,'advance':200,'transport':100,'lodging':0,'settlement':'2026-10-08'},
]
for i,t in enumerate(trips):
    tid=c.ensure('hr_trip_'+str(i),'gt.payroll.trip',{'name':f'DEL-DEMO-2026-{i+1:03}', 'company_id':1,'employee_id':s['hr_employee_'+str(t['employee'])],'policy_id':policy,'kind':t['kind'],'country_id':c.ref(t['country']),'destination':t['destination'],'purpose':'Intervenție și instruire tehnică fictivă','departure':t['departure'],'arrival':t['arrival'],
        'allowance_currency_id':c.ref(t['currency']),'rate':t['rate'],'reference_rate':t['reference_rate'],'fx_rate':t['fx'],'exchange_date':t['departure'][:10],'exchange_source':'Parametri de exercițiu; EUR/RON=5,00 este curs fictiv, nu cotație BNR.',
        'basic_wage':employees[t['employee']][1],'working_days':workdays,'payroll_date':'2026-10-31','settlement_date':t['settlement'],'advance_date':'2026-10-02','advance_amount':t['advance'],'transport_amount':t['transport'],'lodging_amount':t['lodging'],'receipt_note':'Documente fictive de transport/cazare. Sume brute, fără deducere TVA.','reviewed':True})
    trip=c.read('gt.payroll.trip',tid,['state','advance_move_id'])
    if trip['state']=='draft':
        if not trip['advance_move_id']:c.call('gt.payroll.trip','action_advance',[[tid]])
        c.call('gt.payroll.trip','action_approve',[[tid]])
    if c.read('gt.payroll.trip',tid,['state'])['state']=='approved':c.call('gt.payroll.trip','action_settle',[[tid]])

period=c.ensure('hr_period_oct','gt.payroll.period',{'name':'Salarii DEMO / Octombrie 2026','company_id':1,'date_from':'2026-10-01','scheduled_days':22,'policy_id':policy,'payment_date':'2026-10-31','notes':'Trei angajați fictivi. CO și deduceri verificate pentru exemplu. Toate plățile sunt numai înregistrări în banca simulată.'})
if c.read('gt.payroll.period',period,['state'])['state'] in ['draft','calculated']:
    c.call('gt.payroll.period','action_generate',[[period]])
    for i in range(3):
        slip=c.search('gt.payroll.slip',[('period_id','=',period),('employee_id','=',s['hr_employee_'+str(i)])],['state'])[0]
        s['hr_slip_'+str(i)]=slip['id'];c.save()
        if slip['state'] in ['draft','calculated']:
            c.call('gt.payroll.slip','action_sync_leave',[[slip['id']]])
            c.write('gt.payroll.slip',slip['id'],{'leave_daily_rate':500 if i==0 else 0,'bonus':500 if i==1 else 0,'overtime_hours':4 if i==1 else 0,'reviewed':True,
                'notes':'Pontaj DEMO. Pentru Ion, indemnizația CO este introdusă la 500 lei/zi, ipoteză verificată a exemplului; media legală nu se calculează automat.'})
    c.call('gt.payroll.period','action_compute',[[period]])
    c.call('gt.payroll.period','action_post',[[period]])
if c.read('gt.payroll.period',period,['state'])['state']=='posted':c.call('gt.payroll.period','action_pay',[[period]])
c.call('gt.payroll.period','action_check_d112',[[period]])

# A separate open month in the same database for hands-on practice; no November posting.
next_period=c.ensure('hr_period_nov','gt.payroll.period',{'name':'Exercițiu deschis / Noiembrie 2026','company_id':1,'date_from':'2026-11-01','scheduled_days':20,'policy_id':policy,'payment_date':'2026-11-30','notes':'Exercițiu încă necontabilizat. 20 zile de lucru presupunând program luni–vineri și 30 noiembrie zi nelucrătoare. Verificați calendarul aplicabil.'})
c.call('gt.payroll.period','action_generate',[[next_period]])
c.call('gt.payroll.period','action_check_d112',[[next_period]])
for slip in c.search('gt.payroll.slip',[('period_id','=',next_period)],['state']):
    if slip['state']=='draft':c.write('gt.payroll.slip',slip['id'],{'reviewed':True,'notes':'Pontaj fictiv complet pentru exercițiu; poate fi editat înainte de calcul.'})

expense_product=c.ensure('hr_expense_product','product.product',{'name':'Consumabile salariat DEMO','type':'service','can_be_expensed':True,'standard_price':120,'property_account_expense_id':account('628'),'supplier_taxes_id':[(6,0,[])]})
c.ensure('hr_expense_draft','hr.expense',{'name':'Consumabile DEMO - ciornă pentru exercițiu','employee_id':s['hr_employee_0'],'product_id':expense_product,'quantity':1,'total_amount_currency':120,'currency_id':c.ref('base.RON'),'date':'2026-11-02','payment_mode':'own_account','tax_ids':[(6,0,[])]})

# Include salary/CAM expense accounts in the existing closing model, without performing closure.
closing=c.read('l10n.ro.account.period.closing',s['close_expense'],['account_ids'])
for aid in [account('641'),account('646')]:
    if aid not in closing['account_ids']:c.write('l10n.ro.account.period.closing',s['close_expense'],{'account_ids':[(4,aid)]})
c.save()
print('HR, three settled delegations, paid October payroll, open November exercise and draft expense ready on port 8070.')

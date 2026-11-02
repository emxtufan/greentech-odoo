"""Current-state financial, access-contract and report checks for HR demo on 8070."""
import json
from datetime import datetime
from io import BytesIO
from zipfile import ZipFile
from lxml import etree,html
from financial_client import Client, ROOT

c=Client();s=c.state;checks={}
out=ROOT/'logs/hr-payroll-exports';out.mkdir(exist_ok=True)
def check(label,condition,value=True):
    assert condition,(label,value)
    checks[label]=value;print('PASS',label,flush=True)

period=c.read('gt.payroll.period',s['hr_period_oct'],['name','state','total_gross','total_net','total_cost','total_tax','slip_ids','d112_check'])
check('october_paid',period['state']=='paid')
check('three_staff',len(period['slip_ids'])==3)
check('net_total',period['total_net']==19559,period['total_net'])
check('payroll_cost',period['total_cost']==34388,period['total_cost'])
check('d112_not_misrepresented','Generatorul XML D112' in period['d112_check'])
expected=[
    {'cash_gross':11000,'trip_taxable':52.5,'cas':2763,'cass':1105,'income_tax':718,'cam':249,'net_pay':6414},
    {'cash_gross':14225,'trip_taxable':218.75,'cas':3611,'cass':1444,'income_tax':939,'cam':325,'net_pay':8231},
    {'cash_gross':8400,'trip_taxable':0,'cas':2100,'cass':840,'income_tax':546,'cam':189,'net_pay':4914},
]
all_moves=[]
policy=c.read('gt.payroll.policy',s['hr_policy'],['salary_payable_id','advance_account_id','travel_payable_id','bank_journal_id'])
for i,wanted in enumerate(expected):
    slip=c.read('gt.payroll.slip',s['hr_slip_'+str(i)],list(wanted)+['state','move_id','payment_move_id','employee_id','trip_ids'])
    check('salary_'+str(i),slip['state']=='paid' and all(slip[k]==v for k,v in wanted.items()),{k:slip[k] for k in wanted})
    check('trip_included_once_'+str(i),slip['trip_ids']==[s['hr_trip_'+str(i)]])
    for move_field in ['move_id','payment_move_id']:
        mid=slip[move_field][0];all_moves.append(mid)
        lines=c.search('account.move.line',[('move_id','=',mid)],['debit','credit','account_id','amount_residual'])
        check('balanced_'+str(mid),abs(sum(x['debit']-x['credit'] for x in lines))<0.005)
        payable=[x for x in lines if x['account_id'][0]==policy['salary_payable_id'][0]]
        check('salary_reconciled_'+str(mid),bool(payable) and all(x['amount_residual']==0 for x in payable))

for i,wanted in enumerate([(3,225,172.5,52.5,975,475),(3.5,1750,1531.25,218.75,3950,1450),(1,50,50,0,150,-50)]):
    fields=['days','allowance','exempt_amount','taxable_amount','total_amount','remaining_amount']
    trip=c.read('gt.payroll.trip',s['hr_trip_'+str(i)],fields+['state','advance_move_id','expense_move_id','settlement_move_id'])
    check('trip_'+str(i),tuple(trip[f] for f in fields)==wanted and trip['state']=='settled',wanted)
    for key in ['advance_move_id','expense_move_id','settlement_move_id']:
        mid=trip[key][0];all_moves.append(mid)
        lines=c.search('account.move.line',[('move_id','=',mid)],['debit','credit','account_id','amount_residual'])
        check('balanced_'+str(mid),abs(sum(x['debit']-x['credit'] for x in lines))<0.005)
        clearing=[x for x in lines if x['account_id'][0] in [policy['advance_account_id'][0],policy['travel_payable_id'][0]]]
        check('travel_reconciled_'+str(mid),all(x['amount_residual']==0 for x in clearing))
check('fifteen_native_entries',len(set(all_moves))==15,len(set(all_moves)))
check('november_open',c.read('gt.payroll.period',s['hr_period_nov'],['state'])['state']=='draft')
check('six_attendance_entries',c.call('hr.attendance','search_count',[[('employee_id.gt_payroll_demo','=',True)]])==6)
check('two_approved_leaves',c.call('hr.leave','search_count',[[('employee_id.gt_payroll_demo','=',True),('state','=','validate')]])==2)
check('no_email_queue',c.call('mail.mail','search_count',[[]])==0)
check('no_active_cron',c.call('ir.cron','search_count',[[('active','=',True)]])==0)

for model in ['gt.payroll.policy','gt.payroll.period','gt.payroll.slip','gt.payroll.trip','hr.employee','hr.leave','hr.attendance','hr.expense']:
    views=c.call(model,'get_views',[],{'views':[[False,'list'],[False,'form']],'options':{'toolbar':True}})
    for typ in ['list','form']:etree.fromstring(views['views'][typ]['arch'].encode())
    check('views_'+model,True)
for name in ['employees','trips','periods','slips','timesheets','d112','leave','attendance','expenses','policy']:
    action=c.rpc('/web/action/load',{'action_id':c.ref('greentech_hr_payroll_demo.action_'+name)})
    check('menu_'+name,action['type']=='ir.actions.act_window')

for label,xmlid,rid in [('stat','report_payroll',s['hr_period_oct']),('fluturas','report_slip',s['hr_slip_0']),('decont','report_trip',s['hr_trip_1'])]:
    action=c.read('ir.actions.report',c.ref('greentech_hr_payroll_demo.'+xmlid),['report_name','report_type'])
    check('html_print_no_pdf_dependency_'+label,action['report_type']=='qweb-html')
    response=c.session.get(c.base+f"/report/html/{action['report_name']}/{rid}",timeout=120)
    check('render_'+label,response.status_code==200 and 'DEMO' in response.text and 'Traceback' not in response.text,{'status':response.status_code,'bytes':len(response.content)})
    (out/(label+'.html')).write_bytes(response.content)
action=c.call('gt.payroll.period','action_xlsx',[[s['hr_period_oct']]])
rid=s['hr_period_oct'];context={**c.context,'active_model':'gt.payroll.period','active_id':rid,'active_ids':[rid]}
response=c.session.get(c.base+f"/report/xlsx/{action['report_name']}/{rid}",params={'context':json.dumps(context)},timeout=120)
check('xlsx_download',response.status_code==200 and response.content.startswith(b'PK'),response.status_code)
with ZipFile(BytesIO(response.content)) as z:
    check('xlsx_four_sheets',len([n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')])==4)
    workbook_xml=z.read('xl/worksheets/sheet1.xml')
    cells=etree.fromstring(workbook_xml)
    net_total=cells.xpath("//*[local-name()='c'][@r='K8']/*[local-name()='v']/text()")
    check('xlsx_net_cached_total',bool(net_total) and float(net_total[0])==19559,net_total)
(out/'Salarii-DEMO.xlsx').write_bytes(response.content)

# Attempt repeated payments through the same public UI methods; must fail without mutation.
before=c.call('account.move','search_count',[[]])
for model,rid,method in [('gt.payroll.slip',s['hr_slip_0'],'action_pay'),('gt.payroll.trip',s['hr_trip_0'],'action_settle'),('gt.payroll.slip',s['hr_slip_0'],'action_post')]:
    try:c.call(model,method,[[rid]])
    except RuntimeError as error:check('repeat_blocked_'+model+'_'+method,'UserError' in str(error))
    else:raise AssertionError('Duplicate action accepted')
check('no_duplicate_moves',c.call('account.move','search_count',[[]])==before)
page=c.session.get(c.base+'/odoo',timeout=90)
check('application_8070',page.status_code==200)
for url in html.fromstring(page.content).xpath('//script/@src'):
    if url.startswith('/web/assets/'):
        asset=c.session.get(c.base+url,timeout=120)
        check('asset_'+url.split('/')[-1],asset.status_code==200 and len(asset.content)>100)
report={'verified_at':datetime.now().isoformat(),'checks':checks,'summary':period,
        'limits':{'demo_only':True,'d112_xml':False,'anaf_submission':False,'native_pdf_engine':False,'visual_browser_test':False}}
(ROOT/'logs/hr-payroll-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('HR PAYROLL VERIFIED:',len(checks),'checks')

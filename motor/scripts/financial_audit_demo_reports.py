"""Audit current DEMO reports against current ledger, not the original seed snapshot."""
import ast
import configparser
import json
from datetime import datetime
from io import BytesIO
from zipfile import ZipFile
from lxml import html
import psycopg2
from financial_client import Client, ROOT

c = Client()
s = c.state
checks = {}
exports = ROOT / 'logs/financial-exports'
exports.mkdir(exist_ok=True)
def check(name, condition, value=True):
    assert condition, (name, value)
    checks[name] = value
    print('PASS', name, flush=True)

cfg = configparser.RawConfigParser()
cfg.read(ROOT/'config/odoo-financiar.conf',encoding='utf-8')
opt = cfg['options']
conn = psycopg2.connect(host=opt['db_host'],port=opt['db_port'],user=opt['db_user'],password=opt['db_password'],dbname='greentech_financiar_test')
conn.set_session(readonly=True)
with conn.cursor() as cur:
    cur.execute("""SELECT -COALESCE(SUM(l.balance),0) FROM account_move_line l
        JOIN account_move m ON m.id=l.move_id JOIN account_account a ON a.id=l.account_id
        WHERE m.state='posted' AND NOT COALESCE(m.l10n_ro_closing_move,false)
        AND l.date BETWEEN '2026-10-01' AND '2026-10-31'
        AND a.account_type IN ('income','income_other','expense','expense_depreciation','expense_direct_cost')""")
    profit = float(cur.fetchone()[0])
    cur.execute("""SELECT COALESCE(SUM(l.balance),0) FROM account_move_line l
        JOIN account_move m ON m.id=l.move_id JOIN account_account a ON a.id=l.account_id
        WHERE m.state='posted' AND l.date<='2026-10-31' AND a.account_type LIKE 'asset_%%'""")
    assets = float(cur.fetchone()[0])
    cur.execute("""SELECT m.id FROM account_move m JOIN account_move_line l ON l.move_id=m.id
        WHERE m.state='posted' GROUP BY m.id HAVING ABS(SUM(l.balance))>0.005""")
    check('posted_ledger_balanced', not cur.fetchall())
conn.close()

menus = c.search('ir.ui.menu',[('parent_id','=',s['reports_menu'])],['name','action'])
check('three_demo_reports_in_menu',len(menus)==3,menus)
pdf_state = c.call('ir.actions.report','get_wkhtmltopdf_state',[])
summary = {}
for key in ['pnl_report','balance_report','budget_report']:
    rid = s[key]
    action = c.rpc('/web/action/load',{'action_id':s['action_'+key]})
    check(key+'_action',action['res_id']==rid and action['res_model']=='mis.report.instance')
    record = c.call('mis.report.instance','web_read',[[rid]],{'specification':{'id':{}}})
    check(key+'_record_id',record[0]['id']==rid)
    view = c.call('mis.report.instance','get_views',[],{'views':[[action['view_id'][0],'form']]})
    check(key+'_view','mis_report_widget' in view['views']['form']['arch'])
    data = c.call('mis.report.instance','compute',[[rid]])
    check(key+'_formulas',all(not str(cell.get('val_r','')).startswith('#') for row in data['body'] for cell in row['cells']))
    rows = {row['label']:row['cells'] for row in data['body']}
    if key in ['pnl_report','budget_report']:
        value = rows['Rezultat inainte de impozit'][0]['val']
        check(key+'_matches_current_ledger',abs(value-profit)<0.005,value)
        summary[key] = value
    if key=='budget_report':
        check('budget_result',rows['Rezultat inainte de impozit'][1]['val']==24200,24200)
    if key=='balance_report':
        check('balance_control_zero',rows['Control active minus pasiv (trebuie zero)'][0]['val']==0)
        check('balance_matches_all_asset_accounts',abs(rows['Total active'][0]['val']-assets)<0.005,assets)
        summary[key]=assets
    drilldowns = 0
    for row in data['body']:
        for cell in row['cells']:
            if not cell.get('drilldown_arg'):
                continue
            drill = c.call('mis.report.instance','drilldown',[[rid],cell['drilldown_arg']])
            assert drill['type']=='ir.actions.act_window'
            domain = drill.get('domain',[])
            if isinstance(domain,str):
                domain=ast.literal_eval(domain)
            c.call(drill['res_model'],'search_count',[domain])
            drilldowns += 1
    check(key+'_all_drilldown_domains',drilldowns>0,drilldowns)
    for converter, method in [('xlsx','export_xls'),('html','print_pdf')]:
        report = c.call('mis.report.instance',method,[[rid]])
        context = {**c.context, **report.get('context',{}), 'active_model':'mis.report.instance','active_id':rid,'active_ids':[rid]}
        params = {'options':json.dumps(report.get('data') or {}),'context':json.dumps(context)}
        path = f"/report/{converter}/{report['report_name']}/{rid}"
        response = c.session.get(c.base+path,params=params,timeout=120)
        check(key+'_'+converter,response.status_code==200 and len(response.content)>200,{'status':response.status_code,'bytes':len(response.content)})
        if converter=='xlsx':
            with ZipFile(BytesIO(response.content)) as z:
                check(key+'_xlsx_structure',z.testzip() is None and 'xl/workbook.xml' in z.namelist())
        else:
            check(key+'_html_content','Traceback' not in response.text and '<table' in response.text)
            if pdf_state=='ok':
                pdf=c.session.get(c.base+path.replace('/html/','/pdf/'),params=params,timeout=120)
                check(key+'_pdf',pdf.status_code==200 and pdf.content.startswith(b'%PDF'))
                (exports/(key+'.pdf')).write_bytes(pdf.content)
        (exports/(key+'.'+converter)).write_bytes(response.content)
    (exports/(key+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

page=c.session.get(c.base+'/odoo',timeout=60)
tree=html.fromstring(page.content)
asset_urls=tree.xpath('//script/@src')
patch_found=False
for url in asset_urls:
    if '/web/assets/' in url:
        asset=c.session.get(c.base+url,timeout=120)
        check('asset_'+url.split('/')[-1],asset.status_code==200)
        if 'greentech_mis_compat' in asset.text and 'record?.resModel' in asset.text:
            patch_found=True
check('live_asset_contains_widget_patch',patch_found)
closing_action=c.read('ir.actions.act_window',c.ref('l10n_ro_account_period_close.act_account_period_closing_wizard'),['context'])
context=eval(closing_action['context'],{'__builtins__':{}},{'active_id':1})
defaults=c.call('l10n.ro.account.period.closing.wizard','default_get',[['closing_id','date_from','date_to']],context=context)
check('demo_closing_defaults_october',defaults['date_from']=='2026-10-01' and defaults['date_to']=='2026-10-31',defaults)
result={'verified_at':datetime.now().isoformat(),'checks':checks,'summary':summary,'pdf_engine':pdf_state,
        'visual_browser_check':False,'widget_lifecycle_test':'logs/mis-widget-regression.json','ledger_modified':False}
(ROOT/'logs/demo-reports-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('Verified',len(checks),'checks. PDF engine:',pdf_state,'Summary:',summary)

"""Run with Odoo shell; every mutation is rolled back. Meaningful business guards."""
import json
from pathlib import Path
from datetime import datetime,timedelta
from odoo.exceptions import UserError,AccessError

assert env.cr.dbname=='greentech_financiar_test'
s=json.loads(Path('logs/financial-state.json').read_text(encoding='utf-8'))
checks={}
def blocked(label,fn,kind=UserError):
    try:
        with env.cr.savepoint():fn()
    except kind:checks[label]=True
    else:raise AssertionError(label+' should be blocked')

try:
    period=env['gt.payroll.period'].browse(s['hr_period_nov'])
    slip=period.slip_ids[0]
    for label,values in [('unreviewed',{'reviewed':False}),('medical',{'medical_days':1}),('invalid_days',{'worked_days':99}),('negative_bonus',{'bonus':-1}),('unsupported_low_gross',{'basic_wage':1000})]:
        try:
            with env.cr.savepoint():
                slip.write(values)
                slip.action_compute()
                raise AssertionError(label+' accepted')
        except UserError:checks[label]=True
    # Actual native methods, live journal entries and reconciliation, in a rolled-back transaction.
    before=env['account.move'].search_count([])
    period.action_compute();assert period.state=='calculated'
    period.action_post();assert period.state=='posted'
    period.action_pay();assert period.state=='paid'
    assert env['account.move'].search_count([])==before+6
    assert all(m.state=='posted' for m in period.slip_ids.move_id+period.slip_ids.payment_move_id)
    checks['november_compute_post_pay']=True
    blocked('posted_salary_immutable',lambda:slip.write({'bonus':10}))
    blocked('posted_policy_immutable',lambda:period.policy_id.write({'cas_rate':1}))
    blocked('duplicate_payment',lambda:slip.action_pay())
    blocked('forged_state',lambda:env['gt.payroll.trip'].create({'state':'settled'}))
    # Boundary calculations distinguish domestic 12h and foreign half-days.
    template=env['gt.payroll.trip'].browse(s['hr_trip_0'])
    for kind,hours,days in [('domestic',11,0),('domestic',12,1),('domestic',24,1),('domestic',36,2),('foreign',11,.5),('foreign',12,.5),('foreign',13,1),('foreign',24,1),('foreign',36,1.5)]:
        start=datetime(2026,12,1,6)
        trip=template.copy({'name':f'TEST {kind} {hours}','kind':kind,'departure':start,'arrival':start+timedelta(hours=hours),'payroll_date':'2026-12-31','advance_amount':0})
        assert trip.days==days,(kind,hours,trip.days)
    checks['trip_duration_boundaries']=True
    # Employee-only accounts cannot read salary/travel records.
    user=env['res.users'].with_context(no_reset_password=True).create({'name':'Audit access temporary','login':'audit-payroll-temporary','group_ids':[(6,0,[env.ref('base.group_user').id])], 'company_id':env.company.id,'company_ids':[(6,0,[env.company.id])]})
    for model in ['gt.payroll.slip','gt.payroll.period','gt.payroll.trip','gt.payroll.policy']:
        blocked('restricted_'+model,lambda model=model:env[model].with_user(user).search([]),AccessError)
    checks['persisted']=False
finally:
    env.cr.rollback()
Path('logs/hr-payroll-transaction-tests.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
print('HR business checks passed; all temporary postings and test user rolled back.')

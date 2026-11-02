from odoo import models


class PayrollXlsx(models.AbstractModel):
    _name='report.greentech_hr_payroll_demo.payroll_xlsx'
    _inherit='report.report_xlsx.abstract'
    _description='Centralizator salarii, pontaje și pregătire D112 DEMO'

    def generate_xlsx_report(self,workbook,data,periods):
        title=workbook.add_format({'bold':True,'font_size':15,'font_color':'#176B54'})
        header=workbook.add_format({'bold':True,'bg_color':'#176B54','font_color':'white','text_wrap':True})
        number=workbook.add_format({'num_format':'#,##0.00'})
        warning=workbook.add_format({'font_color':'#9C4800','text_wrap':True})
        for period in periods:
            ws=workbook.add_worksheet('Stat '+str(period.id));ws.set_column(0,0,32);ws.set_column(1,12,17)
            ws.merge_range(0,0,0,12,period.name,title)
            ws.merge_range(1,0,1,12,'DATE FICTIVE — CENTRALIZATOR DE TEST — NU ESTE DECLARAȚIA D112',warning)
            labels=['Angajat','Brut salarial','Diurnă impozabilă deja plătită','Diurnă neimpozabilă','Brut fiscal','CAS','CASS','Bază impozit','Impozit','CAM','Net de plată','Cost salarial','Stare']
            for col,label in enumerate(labels):ws.write(3,col,label,header)
            ws.set_row(3,42)
            for row,slip in enumerate(period.slip_ids,4):
                ws.write(row,0,slip.employee_id.name)
                for col,key in enumerate(['cash_gross','trip_taxable','trip_exempt','taxable_gross','cas','cass','tax_base','income_tax','cam','net_pay','employer_cost'],1):ws.write_number(row,col,slip[key],number)
                ws.write(row,12,slip.state)
            end=4+len(period.slip_ids);ws.write(end,0,'TOTAL',header)
            for col in range(1,12):
                values=['cash_gross','trip_taxable','trip_exempt','taxable_gross','cas','cass','tax_base','income_tax','cam','net_pay','employer_cost']
                ws.write_formula(end,col,f'=SUM({chr(65+col)}5:{chr(65+col)}{end})',number,sum(period.slip_ids.mapped(values[col-1])))
            ws.freeze_panes(4,1);ws.autofilter(3,0,end-1,12)
            ts=workbook.add_worksheet('Pontaj '+str(period.id));ts.set_column(0,0,32);ts.set_column(1,7,20)
            for col,label in enumerate(['Angajat','Zile lună','Lucrate','CO','Fără plată','Medical','Ore suplimentare','Verificat']):ts.write(0,col,label,header)
            for row,slip in enumerate(period.slip_ids,1):
                for col,value in enumerate([slip.employee_id.name,period.scheduled_days,slip.worked_days,slip.paid_leave_days,slip.unpaid_days,slip.medical_days,slip.overtime_hours,'Da' if slip.reviewed else 'Nu']):ts.write(row,col,value)
            ds=workbook.add_worksheet('Diurne '+str(period.id));ds.set_column(0,2,30);ds.set_column(3,8,20)
            for col,label in enumerate(['Referință','Angajat','Destinație','Zile','Diurnă RON','Neimpozabil','Impozabil','Avans','Total decont']):ds.write(0,col,label,header)
            for row,trip in enumerate(period.slip_ids.trip_ids,1):
                for col,value in enumerate([trip.name,trip.employee_id.name,trip.destination,trip.days,trip.allowance,trip.exempt_amount,trip.taxable_amount,trip.advance_amount,trip.total_amount]):ds.write(row,col,value,number if col>=3 else None)
            prep=workbook.add_worksheet('Pregatire D112 '+str(period.id));prep.set_column(0,0,110)
            prep.write(0,0,'Pregătire D112 — fără XML validat, fără depunere',title)
            text=period.d112_check or 'Rulați Verifică pregătirea D112 din stat. Firma și angajații sunt fictivi.'
            for row,line in enumerate(text.splitlines(),2):prep.write(row,0,line,warning);prep.set_row(row,40)

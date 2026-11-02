{
    "name": "ANAF - State salariale România",
    "version": "19.0.1.0.0",
    "summary": "Calcul salarial din contractele Odoo și generare D112",
    "author": "Greentech Professionals SRL",
    "license": "AGPL-3",
    "depends": ["greentech_anaf_d112", "hr", "hr_holidays", "hr_attendance"],
    "data": ["security/security.xml", "security/ir.model.access.csv", "views/payroll.xml"],
    "installable": True,
}

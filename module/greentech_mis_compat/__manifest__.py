{
    'name': 'GreenTech - MIS Odoo 19 compatibility',
    'version': '19.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Greentech Professionals SRL',
    'depends': ['mis_builder'],
    'assets': {
        'web.assets_backend': [
            'greentech_mis_compat/static/src/mis_report_compat.js',
        ],
    },
    'installable': True,
}

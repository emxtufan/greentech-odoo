{
    'name': 'Import SAGA - firme, documente și istoric contabil',
    'version': '19.0.1.1.0',
    'author': 'GreenTech',
    'license': 'AGPL-3',
    'depends': ['account', 'l10n_ro', 'hr', 'account_statement_base'],
    'assets': {'web.assets_backend': ['greentech_saga_import/static/src/open_company.js']},
    'data': ['security/security.xml', 'security/ir.model.access.csv', 'views/views.xml', 'views/work.xml'],
    'installable': True,
    'application': False,
}

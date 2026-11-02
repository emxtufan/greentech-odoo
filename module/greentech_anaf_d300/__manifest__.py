{
    "name": "ANAF - D300 Decont TVA",
    "version": "19.0.1.0.0",
    "summary": "D300 2026: contabilitate, trasabilitate, regularizări, XML și validare ANAF",
    "author": "Greentech Professionals SRL",
    "license": "AGPL-3",
    "depends": ["greentech_ro_vat_journals"],
    "external_dependencies": {"python": ["lxml", "pypdf"]},
    "data": ["security/security.xml", "security/ir.model.access.csv", "views/d300.xml"],
    "assets": {"web.assets_backend": [
        "greentech_anaf_d300/static/src/report.js",
        "greentech_anaf_d300/static/src/report.xml",
        "greentech_anaf_d300/static/src/report.scss",
    ]},
    "application": True,
    "installable": True,
}

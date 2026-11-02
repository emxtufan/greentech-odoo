{
    "name": "Jurnale TVA România - cumpărări și vânzări",
    "version": "19.0.1.0.0",
    "author": "Greentech Professionals SRL",
    "license": "AGPL-3",
    "depends": ["account", "l10n_ro_vat_on_payment", "l10n_ro_nondeductible_vat", "greentech_anaf_d112"],
    "external_dependencies": {"python": ["reportlab"]},
    "data": ["security/ir.model.access.csv", "views/journals.xml"],
    "assets": {"web.assets_backend": [
        "greentech_ro_vat_journals/static/src/journal.js",
        "greentech_ro_vat_journals/static/src/journal.xml",
        "greentech_ro_vat_journals/static/src/journal.scss",
    ]},
    "installable": True,
}

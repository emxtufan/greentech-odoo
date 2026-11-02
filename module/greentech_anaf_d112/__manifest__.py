{
    "name": "ANAF - Declarația 112",
    "version": "19.0.1.0.0",
    "summary": "D112: angajator, asigurați, XML, validare oficială și dosarul declarației",
    "author": "Greentech Professionals SRL",
    "license": "AGPL-3",
    "depends": ["account", "l10n_ro", "web"],
    "external_dependencies": {"python": ["lxml", "pypdf"]},
    "data": ["security/security.xml", "security/ir.model.access.csv", "views/d112.xml", "views/settings.xml"],
    "assets": {
        "web.assets_backend": [
            "greentech_anaf_d112/static/src/editor.js",
            "greentech_anaf_d112/static/src/editor.xml",
            "greentech_anaf_d112/static/src/editor.scss",
        ],
    },
    "application": True,
    "installable": True,
}

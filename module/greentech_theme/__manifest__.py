{
    "name": "GreenTech – Temă clean",
    "version": "19.0.1.1.0",
    "category": "Themes/Backend",
    "author": "Greentech Professionals SRL",
    "license": "LGPL-3",
    "depends": ["web"],
    "assets": {
        "web._assets_primary_variables": [
            ("before", "web/static/src/scss/primary_variables.scss", "greentech_theme/static/src/scss/primary_variables.scss"),
        ],
        "web.assets_backend": [
            "greentech_theme/static/src/scss/fonts.scss",
            "greentech_theme/static/src/scss/theme.scss",
            "greentech_theme/static/src/js/dashboard_graph_patch.js",
        ],
    },
    "installable": True,
}

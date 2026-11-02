# -*- coding: utf-8 -*-
# Copyright 2026 Transilvania Business Suite
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "ANAF DUKIntegrator",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "countries": ["ro"],
    "summary": "Validate Romanian ANAF tax declarations with the official DUKIntegrator tool",
    "description": """
ANAF DUKIntegrator Validator
=============================

Runs Romania's official ANAF **DUKIntegrator** tool (the same Java validator
ANAF itself uses) against a declaration XML you already generated, and
returns a pass/fail verdict plus the flat confirmation PDF DUKIntegrator
produces on success.

**How it works**

This module talks to your own, self-hosted DUKIntegrator installation
(the ``.jar`` files ANAF distributes) over a local subprocess call - no
external HTTP service, no per-request fee, no vendor account required.
You install DUKIntegrator once on the server (or point the module at an
existing install) and every declaration validation runs locally.

**What you get**

* One service (``anaf.duk.validator``) any Odoo module or script can call
  with an XML string + a declaration code (D100, D101, D112, D205, D300,
  D394) to get back a validation verdict.
* Optional confirmation PDF generation (DUKIntegrator's own flat PDF
  output) for accepted declarations.
* Settings page field for the DUKIntegrator installation path - no
  server/code access needed to point it at a different install.
* Clear, actionable error message when DUKIntegrator isn't installed or
  isn't where the setting says it is.

**Requirements**

* Java runtime on the Odoo server.
* DUKIntegrator ``.jar`` files, downloaded from ANAF's own distribution
  (not included - see the README for where to get them).

This module only runs the validator; it does not generate declaration XML.
Pair it with a declaration-generation module (Romanian accounting modules,
including TBS's own **Romania Tax Declarations**, wire directly into it).
    """,
    "author": "Transilvania Business Suite",
    "website": "https://transilvaniabusinesssuite.ro",
    "support": "contact@xtbs.ro",
    "license": "LGPL-3",

    "depends": ["base"],

    "data": [
        "views/res_config_settings_views.xml",
    ],

    "images": ["static/description/banner.png"],

    "installable": True,
    "application": False,
    "auto_install": False,
}

# Copyright (C) 2023 Terrabit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).


import logging


def pre_init_hook(env):
    # A bundled test snapshot is not evidence of the current ANAF status.
    # Keep the existing registry, if any; the ANAF update action obtains it.
    logging.getLogger(__name__).info(
        "ANAF VAT registry is populated by the explicit update action; "
        "installation does not overwrite it with a test fixture."
    )

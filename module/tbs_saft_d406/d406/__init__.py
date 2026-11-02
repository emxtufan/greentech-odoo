# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Pure-Python core of the D406 SAF-T generator.

Nothing in this package imports Odoo. That is deliberate: the rules encoded
here (element ordering, the "no empty element" invariant, RegistrationNumber
prefixes, IBAN/account sanitisation) are the parts that DUKIntegrator rejects
files over, so they must be unit-testable without a database.

The Odoo layer in ``models/`` and ``wizard/`` is responsible only for
*collecting* data and handing plain dicts to this package.
"""

from . import sanitize
from . import registration
from . import xmlbuilder
from . import accountmap

# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""SAF-T ``RegistrationNumber`` / ``CustomerID`` / ``SupplierID`` construction.

Source of truth: the ANAF workbook ``RO_SAFT_SchemaDefCod_16.02.2026.xlsx``,
sheet ``5. Structures``, rows S.CMH.1 (CompanyHeaderStructure), S.C.1
(CompanyStructure), S.I.23 (CustomerInfo) and S.I.26 (SupplierInfo).

Two distinct rules live in that sheet and they are easy to conflate:

* **The reporting company's own header** (``Header/Company/RegistrationNumber``,
  S.CMH.1) carries **no two-digit type prefix**. A resident registered for VAT
  reports its VAT number *with* the ``RO`` prefix; otherwise its CUI. A
  non-resident with Romanian fiscal registration reports its CIF.
* **Every partner** (customer, supplier, owner) carries a **two-digit type
  prefix** followed by the identifier, and there the ``RO`` fiscal attribute is
  explicitly excluded.

Getting these backwards is a silent data error, not a schema error: DUK will
accept it.
"""
from __future__ import annotations

from . import sanitize

#: EU member states, used to pick 01 vs 02 (VAT-registered) and 05 vs 06
#: (not VAT-registered). Romania is excluded on purpose: a Romanian partner
#: is always type 00 or 03, never 01/05.
EU_COUNTRY_CODES = frozenset({
    'AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GR',
    'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PL', 'PT', 'SE',
    'SI', 'SK',
})

#: Greece files VAT numbers under ``EL`` while ISO 3166-1 calls it ``GR``.
#: The ANAF example ``01EL123456789`` shows ANAF expects the VAT-style code.
VAT_COUNTRY_OVERRIDES = {'GR': 'EL'}

#: Type 08 + 13 zeros: the single legal placeholder for an unidentified
#: retail customer. ANAF restricts it to point-of-sale transactions and
#: forbids it for SupplierID.
UNIDENTIFIED_CUSTOMER_ID = '08' + '0' * 13


class PartnerIdentity:
    """The subset of partner data needed to build a SAF-T identifier.

    Deliberately a plain object rather than an Odoo recordset so the rules
    below can be unit-tested without a database.
    """

    __slots__ = ('name', 'vat', 'company_registry', 'country_code',
                 'is_company', 'partner_ref', 'partner_id')

    def __init__(self, name='', vat='', company_registry='', country_code='',
                 is_company=True, partner_ref='', partner_id=None):
        self.name = name
        self.vat = vat
        self.company_registry = company_registry
        self.country_code = (country_code or '').upper()
        self.is_company = is_company
        self.partner_ref = partner_ref
        self.partner_id = partner_id

    def fallback_code(self) -> str:
        """The operator-assigned code used by types 04, 05 and 06."""
        ref = sanitize.text(self.partner_ref).replace(' ', '')
        if ref:
            return ref
        return str(self.partner_id) if self.partner_id else ''


def _vat_country(identity: PartnerIdentity) -> str:
    """Best available 2-letter country for VAT purposes."""
    from_vat = sanitize.vat_country(identity.vat)
    country = from_vat or identity.country_code
    return VAT_COUNTRY_OVERRIDES.get(country, country)


def _romanian_fiscal_code(identity: PartnerIdentity) -> str:
    """CUI for a Romanian partner, from VAT first then company registry.

    ``company_registry`` holds the trade-register number (``J40/10200/2009``)
    for many Romanian records. :func:`sanitize.cui` rejects that shape, which
    is what prevents the confirmed DUK rejection
    ``RegistrationNumber 00J40/10200/2009 formatul este invalid``.
    """
    return sanitize.cui(identity.vat) or sanitize.cui(identity.company_registry)


def partner_registration_number(identity: PartnerIdentity,
                                is_customer: bool = True) -> str:
    """Build the prefixed SAF-T identifier for a partner.

    Returns ``''`` when no identifier can be built at all; the caller decides
    the fallback (see :func:`unclassified_partner_id`) rather than this
    function inventing one.
    """
    country = _vat_country(identity)
    vat_body = sanitize.vat_number(identity.vat)

    # Type 03 - natural persons (CNP / NIF).
    if not identity.is_company:
        personal_code = sanitize.cui(identity.vat) or sanitize.cui(identity.company_registry)
        if personal_code:
            return '03' + personal_code
        # Type 04 - individual who does not disclose a CNP (e-commerce).
        fallback = identity.fallback_code()
        return '04' + fallback if fallback else ''

    # Type 00 - Romanian economic operator, CUI without the RO attribute.
    if country == 'RO' or (not country and _romanian_fiscal_code(identity)):
        cui_code = _romanian_fiscal_code(identity)
        return '00' + cui_code if cui_code else ''

    if not country:
        return ''

    # Types 01 / 02 - foreign operator WITH a VAT identification code.
    if vat_body:
        prefix = '01' if country in EU_COUNTRY_CODES else '02'
        return f'{prefix}{country}{vat_body}'

    # Types 05 / 06 - foreign operator WITHOUT VAT registration. The country
    # code must be upper case and the identifier is the one we assign.
    # This is the branch Enterprise gets wrong: it falls through to
    # "02" + a defaulted "ro" + an empty number, producing the confirmed
    # rejection ``Pentru RegistrationNumber 02ro formatul este invalid``.
    fallback = identity.fallback_code()
    if not fallback:
        return ''
    prefix = '05' if country in EU_COUNTRY_CODES else '06'
    return f'{prefix}{country}{fallback}'


def company_header_registration_number(identity: PartnerIdentity) -> str:
    """Build ``Header/Company/RegistrationNumber`` for the reporting company.

    Per S.CMH.1 this field takes **no** two-digit type prefix: a resident
    registered for VAT reports the VAT number *including* the ``RO`` prefix,
    everyone else reports the bare CUI/CIF.
    """
    vat = sanitize.text(identity.vat).upper().replace(' ', '')
    if vat.startswith('RO') and sanitize.cui(vat):
        return vat
    bare = _romanian_fiscal_code(identity)
    if bare:
        return bare
    return sanitize.text(identity.company_registry).replace(' ', '')


def unclassified_partner_id(company_registration_number: str) -> str:
    """Identifier for a transaction partner we cannot classify.

    Card payments to foreign merchants (advertising, SaaS, hosting) leave
    journal items whose partner is neither a customer nor a supplier with a
    balance, so both ``CustomerID`` and ``SupplierID`` came out as ``0`` —
    a confirmed DUK rejection. The reference file accepted by ANAF resolves
    this by repeating the reporting company's own identifier on both sides,
    so that is what we do.

    Note that ANAF's type 08 placeholder is *not* usable here: the workbook
    restricts it to point-of-sale transactions and forbids it for
    ``SupplierID``.
    """
    return company_registration_number

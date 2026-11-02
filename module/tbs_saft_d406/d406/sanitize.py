# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Value sanitisation for SAF-T D406.

Every function here exists because DUKIntegrator rejected a real production
file over the raw value. Each one carries the rejection message it prevents.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# SAF-T monetary/quantity fields are fixed-point; ANAF rejects scientific
# notation and accepts at most 2 decimals on monetary values.
MONETARY_EXP = Decimal('0.01')
QUANTITY_EXP = Decimal('0.0001')

_WHITESPACE_RE = re.compile(r'\s+')
_NON_ALNUM_RE = re.compile(r'[^A-Za-z0-9]')
_DIGITS_RE = re.compile(r'\d+')

#: Control characters XML 1.0 forbids outside tab/newline/carriage return.
#: lxml raises ``ValueError: All strings must be XML compatible`` on
#: assignment, which would surface as a bare traceback mid-export. They reach
#: partner and product names routinely through CSV, bank-statement and
#: e-invoice imports, so they are stripped rather than allowed to abort a
#: declaration.
_ILLEGAL_XML_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def text(value, max_length: int | None = None) -> str:
    """Normalise any value to a trimmed single-spaced string.

    Returns ``''`` for None/blank so callers can apply the no-empty-element
    rule uniformly (see :mod:`.xmlbuilder`).
    """
    if value is None or value is False:
        return ''
    result = _ILLEGAL_XML_RE.sub('', str(value).replace('\xa0', ' '))
    result = _WHITESPACE_RE.sub(' ', result).strip()
    if max_length is not None and len(result) > max_length:
        result = result[:max_length].strip()
    return result


def iban(value) -> str:
    """Strip spaces and upper-case an IBAN.

    DUK: ``Pentru IBANNumber 'RO49 AAAA 1B31 0075 9384 0000' formatul este
    invalid pentru codul tarii 'RO'``. The values are clean in the database;
    the spaces come from rendering ``acc_number`` raw. Always feed this
    function (or Odoo's ``sanitized_acc_number``) into ``<IBANNumber>``.
    """
    return _NON_ALNUM_RE.sub('', text(value)).upper()


def account_id(value) -> str:
    """Return the numeric part of a chart-of-accounts code.

    DUK: ``eroare atribut: numar intreg eronat: '581.Stripe'``. ``AccountID``
    must be strictly numeric, so a code carrying a human suffix has to be
    reduced to its leading digits. Returns ``''`` when there are no leading
    digits at all, which the pre-flight validator reports as a blocking error
    rather than silently exporting a wrong account.
    """
    stripped = text(value)
    match = re.match(r'\d+', stripped)
    return match.group(0) if match else ''


def is_numeric_account(value) -> bool:
    """True when a chart code is already purely numeric (nothing to strip)."""
    stripped = text(value)
    return bool(stripped) and stripped.isdigit()


def vat_number(value) -> str:
    """Normalise a VAT / CUI to its bare form, dropping the country prefix.

    ``RO12345674`` -> ``12345674``. Non-Romanian VATs keep their national
    part; the country code is emitted separately by
    :mod:`.registration`.
    """
    cleaned = _NON_ALNUM_RE.sub('', text(value)).upper()
    if cleaned[:2].isalpha():
        return cleaned[2:]
    return cleaned


def vat_country(value) -> str:
    """Return the 2-letter country prefix of a VAT number, or ``''``."""
    cleaned = _NON_ALNUM_RE.sub('', text(value)).upper()
    return cleaned[:2] if cleaned[:2].isalpha() else ''


def cui(value) -> str:
    """Normalise a Romanian CUI to digits only.

    DUK: ``RegistrationNumber 00J40/10200/2009 formatul este invalid``. That
    rejection happens when the trade-register number (``J40/...``) is used
    instead of the fiscal code. Anything that is not a run of digits is
    rejected here so the caller falls back rather than emitting ``J40/``.
    """
    cleaned = text(value).upper().replace(' ', '')
    # A trade register number (J40/10200/2009, F12/..., C.../...) is never a CUI.
    if re.match(r'^[JFC]\d{1,2}/', cleaned):
        return ''
    digits = _NON_ALNUM_RE.sub('', cleaned)
    if digits[:2] == 'RO':
        digits = digits[2:]
    return digits if digits.isdigit() else ''


def monetary(value) -> str:
    """Format a monetary amount with exactly 2 decimals, no exponent."""
    return _quantise(value, MONETARY_EXP)


def quantity(value) -> str:
    """Format a quantity with up to 4 decimals, no exponent."""
    return _quantise(value, QUANTITY_EXP)


def _quantise(value, exponent: Decimal) -> str:
    if value is None or value is False or value == '':
        value = 0
    try:
        dec = Decimal(str(value)).quantize(exponent, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, ArithmeticError):
        dec = Decimal('0').quantize(exponent)
    # Normalise "-0.00" to "0.00": ANAF has no concept of negative zero and
    # the string comparison in DUK's totals check is literal.
    if dec == 0:
        dec = abs(dec)
    return f'{dec:f}'


def region_code(country_code, state_code) -> str:
    """Return the SAF-T ``<Region>`` value, or ``''`` when it must be omitted.

    DUK: ``Pentru tara 'IE' codul regiunii nu trebuie completat``. ANAF only
    accepts a region for Romania, formatted ``RO-XX``. Emitting it for
    IE-D / US-CA / CA-ON is a hard rejection, so every non-RO country
    returns ``''`` and the element is dropped.
    """
    if text(country_code).upper() != 'RO':
        return ''
    code = _NON_ALNUM_RE.sub('', text(state_code)).upper()
    if not code:
        return ''
    return f'RO-{code}'

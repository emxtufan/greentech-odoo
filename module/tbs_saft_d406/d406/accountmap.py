# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Resolve an Odoo chart-of-accounts code onto the ANAF nomenclature.

Background: the Romanian statutory chart published by ANAF uses 1-to-4 digit
synthetic accounts (``1``, ``10``, ``101``, ``1012``). Odoo's ``l10n_ro``
chart pads them out to 6 digits (``101200``) and lets users add their own
analytic suffixes. Measured against the 579 accounts in the standard Odoo RO
chart, 387 match an ANAF code exactly and the remaining 192 resolve by
truncating the trailing padding — none are unmappable.

That measurement is what makes this a *computed* field with a manual override
rather than a 600-row mapping table the customer has to fill in by hand.

The matching rule below is **not** guesswork: it mirrors the algorithm
disassembled from ``D406Validator.jar``
(``d406validator.v0.ValidatorExtension1Impl.validateAccountId``):

1. Take the first three characters of the ``AccountID`` (or the whole code
   if it is shorter) and look that *root* up in the statutory chart. If the
   root is absent, the file is rejected outright with
   ``ID-ul contului [...] trebuie sa se gaseasca in planul de conturi``.
2. Extend the prefix one digit at a time, each time narrowing the candidate
   set to the chart entries starting with the prefix matched so far.
3. As soon as no chart entry starts with the current prefix, stop and accept
   the remaining digits unchecked.

That is exactly why ``101200`` is accepted (root ``101`` exists, ``1012``
exists, nothing longer does, so the trailing ``00`` is free) while ``899000``
is rejected (root ``899`` does not exist; ANAF defines only ``891`` and
``892`` under class ``89``).
"""
from __future__ import annotations

from . import sanitize

#: Length of the root the validator anchors on before walking forward.
#: Codes shorter than this are looked up whole.
ROOT_LENGTH = 3


class Resolution:
    """Outcome of resolving one account code."""

    __slots__ = ('code', 'anaf_code', 'method', 'message')

    EXACT = 'exact'
    PREFIX = 'prefix'
    OVERRIDE = 'override'
    UNRESOLVED = 'unresolved'
    NOT_NUMERIC = 'not_numeric'

    def __init__(self, code, anaf_code, method, message=''):
        self.code = code
        self.anaf_code = anaf_code
        self.method = method
        self.message = message

    @property
    def is_resolved(self) -> bool:
        return self.method in (self.EXACT, self.PREFIX, self.OVERRIDE)

    def __repr__(self):
        return (f'<Resolution {self.code!r} -> {self.anaf_code!r} '
                f'({self.method})>')


def prefix_index(anaf_codes) -> frozenset:
    """Every prefix of every chart code.

    Lets the walk in :func:`resolve` ask "does the chart still have anything
    more specific than this?" in constant time instead of scanning all 600+
    codes for each character of each account.
    """
    prefixes = set()
    for entry in anaf_codes:
        for length in range(1, len(entry) + 1):
            prefixes.add(entry[:length])
    return frozenset(prefixes)


def resolve(code, anaf_codes, override=None,
            root_length: int = ROOT_LENGTH, prefixes=None) -> Resolution:
    """Map one Odoo account code onto an ANAF nomenclature code.

    Mirrors the validator's own walk, so a code this function resolves is a
    code DUKIntegrator accepts, and the returned ``anaf_code`` is the most
    specific statutory account the code belongs to — which is what
    ``StandardAccountID`` should carry.

    :param code: the Odoo account code, e.g. ``101200`` or ``581.Stripe``.
    :param anaf_codes: a container of valid ANAF codes (``set`` recommended).
    :param override: a manually configured ANAF code that wins outright.
    """
    raw = sanitize.text(code)

    if override:
        return Resolution(raw, sanitize.text(override), Resolution.OVERRIDE)

    numeric = sanitize.account_id(raw)
    if not numeric:
        return Resolution(
            raw, '', Resolution.NOT_NUMERIC,
            f'Account code {raw!r} has no leading digits, so SAF-T '
            f'<AccountID> cannot be derived. Set a manual SAF-T code on '
            f'the account.'
        )

    # Step 1 - the root must exist, otherwise the validator rejects outright.
    root = numeric[:root_length]
    if root not in anaf_codes:
        return Resolution(
            raw, '', Resolution.UNRESOLVED,
            f'Account code {raw!r} has no counterpart in the ANAF chart of '
            f'accounts: its root {root!r} is not a statutory account. '
            f'DUKIntegrator rejects this file. Either re-code the account '
            f'or set a manual SAF-T code on it.'
        )

    # Step 2 - extend one character at a time while the chart still has a
    # more specific entry. The last entry that exists is the statutory
    # account this code rolls up to.
    if prefixes is None:
        prefixes = prefix_index(anaf_codes)
    matched = root
    for length in range(root_length + 1, len(numeric) + 1):
        candidate = numeric[:length]
        if candidate in anaf_codes:
            matched = candidate
            continue
        # Step 3 - no chart entry starts with this prefix: the remaining
        # digits are the taxpayer's own analytic detail and are not checked.
        if candidate not in prefixes:
            break

    method = Resolution.EXACT if matched == numeric else Resolution.PREFIX
    return Resolution(raw, matched, method)


def resolve_many(codes, anaf_codes, overrides=None,
                 root_length: int = ROOT_LENGTH) -> dict:
    """Resolve a batch of codes, returning ``{code: Resolution}``."""
    overrides = overrides or {}
    prefixes = prefix_index(anaf_codes)
    return {
        code: resolve(code, anaf_codes, overrides.get(code), root_length,
                      prefixes)
        for code in codes
    }


def summarise(resolutions) -> dict:
    """Count resolutions by method — used by the pre-flight report."""
    counts = {}
    for resolution in resolutions:
        counts[resolution.method] = counts.get(resolution.method, 0) + 1
    return counts


#: Odoo ``account_type`` -> SAF-T ``AccountType`` (``Activ`` / ``Pasiv`` /
#: ``Bifunctional``). The SAF-T enum is the Romanian statutory notion of
#: account direction, which Odoo does not model, so this is the closest
#: faithful mapping. Accounts whose real behaviour is two-way (VAT
#: settlement, current accounts with associates) are best set explicitly on
#: the account; that is what the manual override field is for.
ODOO_TYPE_TO_SAFT_TYPE = {
    'asset_receivable': 'Activ',
    'asset_cash': 'Activ',
    'asset_current': 'Activ',
    'asset_non_current': 'Activ',
    'asset_prepayments': 'Activ',
    'asset_fixed': 'Activ',
    'liability_payable': 'Pasiv',
    'liability_credit_card': 'Pasiv',
    'liability_current': 'Pasiv',
    'liability_non_current': 'Pasiv',
    'equity': 'Pasiv',
    'equity_unaffected': 'Bifunctional',
    'income': 'Pasiv',
    'income_other': 'Pasiv',
    'expense': 'Activ',
    'expense_depreciation': 'Activ',
    'expense_direct_cost': 'Activ',
    'off_balance': 'Bifunctional',
}

DEFAULT_SAFT_ACCOUNT_TYPE = 'Bifunctional'


def saft_account_type(odoo_account_type, override=None) -> str:
    """Return the SAF-T ``AccountType`` for an Odoo account type."""
    if override:
        return override
    return ODOO_TYPE_TO_SAFT_TYPE.get(
        odoo_account_type, DEFAULT_SAFT_ACCOUNT_TYPE)

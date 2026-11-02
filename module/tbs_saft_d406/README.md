# Romania — D406 SAF-T Export (`tbs_saft_d406`)

Generates the ANAF **D406 SAF-T** declaration on **Odoo 19 Community**.

Odoo's own SAF-T support (`account_saft`, `l10n_ro_saft`) is Enterprise-only and
is bolted onto the `account_reports` General Ledger report, which Community does
not have. This module is an independent implementation that runs on plain
Community.

> **Status:** phase 1 — the periodic declarations (**L**, **T**, **NL**, **NT**).
> The annual (**A**, fixed assets) and on-demand (**C**, stock) declarations are
> out of scope; see [Scope](#scope).

---

## Why this module exists

Verified as of 2026-08-14:

- Odoo Community `src/addons` contains **no** `*saft*` module, and OCA's
  `l10n_romania19` has eight accounting modules and **zero** SAF-T.
- There is **no open-source D406 generator under a usable licence**
  (MIT/BSD/Apache/LGPL) anywhere on GitHub or PyPI. The projects that exist are
  either AGPL-3, unlicensed (all rights reserved), or republished Enterprise
  code.
- From 2026 **every** Romanian taxpayer files D406.

So on Community the options were a €172–12,500 proprietary module, an Enterprise
subscription, or nothing.

## What it does

| Section | Status |
|---|---|
| `Header` | full, incl. `TaxAccountingBasis` and declaration-type gating |
| `MasterFiles/GeneralLedgerAccounts` | full, with own balance aggregation |
| `MasterFiles/Customers` · `Suppliers` | full, incl. the 8 ANAF identifier types |
| `MasterFiles/TaxTable` | full, from the ANAF nomenclature |
| `MasterFiles/UOMTable` | full, **including the mandatory `Description`** |
| `MasterFiles/AnalysisTypeTable` | populated from analytic plans |
| `MasterFiles/Products` | full |
| `GeneralLedgerEntries` | full, SQL aggregation written from scratch |
| `SourceDocuments/SalesInvoices` · `PurchaseInvoices` | full |
| `SourceDocuments/Payments` | full |
| `MasterFiles/Assets` · `SourceDocuments/AssetTransactions` | empty (declaration A) |
| `MasterFiles/PhysicalStock` · `MovementOfGoods` | empty (declaration C) |

## Installation

```
depends: account, l10n_ro
```

No Enterprise modules, no OCA requirement, no external Python packages beyond
what Odoo already ships (`lxml`).

## Usage

**Accounting → Reporting → D406 SAF-T → Export D406 SAF-T**

1. **Check Configuration** — reports unmapped accounts and taxes *before*
   generating, so problems surface on a screen you can act on rather than on
   ANAF's rejection notice.
2. **Generate** — builds the file and validates it against the official XSD.
3. **Validate with DUKIntegrator** — appears only if `tbs_anaf_duk_validator`
   is installed (soft-detected; there is no dependency on it).
4. **Download**.

### Configuration you must do once

| Where | What |
|---|---|
| Company | SAF-T accounting basis (usually `I`), phone, at least one bank account with a valid IBAN |
| Taxes | SAF-T tax type + 6-digit tax code on every active tax |
| Accounts | Review anything the pre-flight check flags (see below) |

## Two things every Romanian Odoo database hits

**1. The `999` accounts.** Odoo *core* (not the Romanian localisation) creates
"Cash Difference Gain"/"Loss" and the cash-discount accounts with a hardcoded
`999` prefix. ANAF's chart has no `999` class, so DUKIntegrator rejects them.
Set a manual SAF-T code on those accounts (Account form → SAF-T D406 → *SAF-T
Account Code (manual)*), mapping them onto whichever statutory account your
accountant uses.

**2. Chart mapping is automatic.** Of the 579 accounts in the standard Odoo RO
chart, every statutory one resolves onto ANAF's nomenclature — exactly or by
prefix. There is no 600-row mapping table to fill in. The compute mirrors the
algorithm disassembled from `D406Validator.jar`, so a code this module resolves
is a code DUKIntegrator accepts.

## Why XSD validation is not enough

The schema does not encode ANAF's business rules, and in places it actively
contradicts the validator. Confirmed by running the official
`DUKIntegrator_AnLunaUI.jar` against generated files:

| Rule | XSD says | DUKIntegrator says |
|---|---|---|
| Root namespace | `mfp:anaf:dgti:d406t:declaratie:v1` | **`...d406:...`** (without the `t`) — rejects the schema's own target namespace |
| `Owners/Owner` | `0..unbounded` | `min:0, max:0` in a periodic declaration |
| `Payments/Payment` | `0..unbounded` | at least 1 required |
| `MasterFiles/Assets` | mandatory container | accepted empty in L/T |

The module emits what **DUKIntegrator** accepts, because that is the gate a real
submission passes. XSD validation still runs on every export — the namespace is
swapped in memory first — because it catches element ordering and missing
mandatory children immediately and for free.

**Always run DUKIntegrator before submitting.** Schema validity is necessary,
not sufficient.

## Nomenclatures

Six ANAF nomenclatures ship as data, generated from the official workbook
`RO_SAFT_SchemaDefCod_16.02.2026.xlsx`:

| Model | Rows | Source sheet |
|---|---:|---|
| `l10n.ro.d406.tax.type` | 354 | `TAX-IMP - Impozite` |
| `l10n.ro.d406.tax.code` | 969 | `Livrari` + `Achizitii*` |
| `l10n.ro.d406.account` | 648 | `PlanConturiBalSocCom` |
| `l10n.ro.d406.uom.code` | 2163 | `Unitati_masura` |
| `l10n.ro.d406.invoice.type` | 43 | `Nom_Tipuri_facturi` |
| `l10n.ro.d406.payment.method` | 5 | `Nom_Mecanisme_plati` |

Includes the **21% / 11% VAT rates valid from 2025-08-01** (340 codes).

### Refreshing them when ANAF republishes

```bash
python3 tools/generate_nomenclature.py --workbook <new.xlsx>
python3 tools/generate_nomenclature.py --check   # CI gate: fails on drift
```

The generator locates header rows by caption, never by index, so it survives
ANAF reformatting the workbook. Provenance (source file, SHA-256, row counts,
data-quality findings) is written to `data/nomenclature/PROVENANCE.md`.

## Architecture

```
d406/                  pure Python, no Odoo import — unit-testable without a DB
  sanitize.py          value normalisation; every function prevents a real rejection
  registration.py      the 8 ANAF identifier types (00-08)
  accountmap.py        chart resolution, mirroring the validator's own walk
  xmlbuilder.py        lxml wrapper enforcing "never emit an empty element"
models/
  d406_generator*.py   sections, split across three files by schema area
  d406_validator.py    XSD + soft DUKIntegrator detection
tools/
  generate_nomenclature.py
```

Two deliberate choices:

- **A builder, not a QWeb template.** The "no empty element" rule must hold for
  ~250 elements. As `t-if` guards that is 250 chances to forget one; here it is
  one `if` in `Node.add`.
- **A pure-Python core.** The rules ANAF rejects files over are testable without
  a database, so they are, and fast.

## Licensing

LGPL-3. Clean-room: the implementation derives from the ANAF XSD, the ANAF
workbook, and the observable behaviour of the public DUKIntegrator validator.
No code or data structure was taken from Odoo Enterprise's `account_saft` /
`l10n_ro_saft` (OEEL-1), nor from any AGPL or unlicensed third-party project.

## Testing

```bash
odoo-bin -d <db> -u tbs_saft_d406 --test-enable --test-tags /tbs_saft_d406
```

36 tests. The golden test generates a file from synthetic data and validates it
against the official XSD. All fixture data is synthetic — no customer data.

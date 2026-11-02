# Changelog

All notable changes to `tbs_saft_d406` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [19.0.1.0.0] - 2026-08-14

Initial implementation — phase 1. Produces the periodic D406 SAF-T
declarations (L, T, NL, NT) on Odoo 19 Community.

### Added

- **Module skeleton** — LGPL-3, depends only on `account` and `l10n_ro`. No
  Enterprise, no OCA, no extra Python packages.
- **Six ANAF nomenclatures** (4,182 rows) generated from the official workbook
  `RO_SAFT_SchemaDefCod_16.02.2026.xlsx`: tax types (354), tax codes (969),
  chart of accounts (648), UN/ECE units (2,163), invoice types (43), payment
  methods (5). Includes the 21% / 11% VAT rates effective 2025-08-01.
- **Repeatable nomenclature generator** (`tools/generate_nomenclature.py`) with
  a `--check` drift gate for CI. Header rows are located by caption rather than
  index so the script survives ANAF reformatting the workbook. Emits provenance
  (source SHA-256, row counts, data-quality findings).
- **Chart-of-accounts mapping** as a computed field with a per-company manual
  override, plus a pre-flight report listing accounts DUKIntegrator would
  reject.
- **General Ledger aggregation** written from scratch in SQL, since
  `account_reports` does not exist in Community. Profit-and-loss accounts
  restart at the fiscal year boundary, balance-sheet accounts carry forward,
  matching Romanian trial-balance semantics.
- **XML generation** for Header, MasterFiles, GeneralLedgerEntries and
  SourceDocuments (sales invoices, purchase invoices, payments).
- **Validation**: XSD against the official schema shipped in the module, plus
  soft detection of `tbs_anaf_duk_validator` for a full DUKIntegrator run. The
  DUK bridge is optional — there is no dependency on it.
- **Export wizard** under Accounting → Reporting → D406 SAF-T, with a
  configuration pre-flight check that runs before generation.
- **38 tests**, including a golden test that generates a file from synthetic
  data and validates it against the official XSD.
- **Apps Store packaging** — icon, banner and English `static/description`
  page, for publication on apps.odoo.com as a free (LGPL-3) module.

### Hardened before publication

Found in the pre-publication review and fixed on the same branch:

- **A period with no bank or cash movement is now refused** with an
  explanatory error. DUKIntegrator requires at least one `Payment` entry, so
  an empty `Payments` section has no valid representation; the export used to
  emit the file anyway and let DUK reject it without an explanation.
- **XML is parsed with entity resolution and DTD loading disabled.** The
  validator entry points accept caller-supplied bytes, and lxml resolves
  external entities by default on the versions Odoo pins — a local-file read
  primitive on the customer's server.
- **The validator and generator entry points are `@api.private`**, so they are
  no longer callable over RPC by any authenticated user.
- **`AnalysisTypeTable` and `MovementTypeTable` are scoped to the reporting
  company.** In a multi-company database they previously exported sibling
  companies' analytic codes and operation types into the declaration.
- **The export asserts the company boundary explicitly.** The ledger
  aggregation is raw SQL, which record rules do not reach.
- **Control characters are stripped from free text.** They arrive routinely
  through CSV, bank-statement and e-invoice imports, and lxml refuses them,
  which aborted the export with a bare traceback.

### Verified against the real validator

The generated file passes `DUKIntegrator_AnLunaUI.jar` (build 2026-02-16) with
zero errors: *"Validare fara erori fisier"*. Getting there settled four points
where the official XSD and the official validator disagree — in each case the
validator wins, because it is the gate a submission actually passes:

- **Root namespace.** The XSD declares `targetNamespace` as
  `mfp:anaf:dgti:d406t:declaratie:v1`, but DUKIntegrator rejects exactly that
  and demands `mfp:anaf:dgti:d406:declaratie:v1` (no `t`). The module emits
  DUK's namespace and swaps it in memory for XSD validation, so both checks
  still run.
- **`Owners/Owner`** is `0..unbounded` in the schema but `min:0, max:0` in a
  periodic declaration — the container must be empty.
- **`Payments/Payment`** is optional in the schema but requires at least one
  entry.
- **`MasterFiles/Assets`** is a mandatory container that must be present but
  empty for L/T.

### Fixed from the start

Traps confirmed by DUKIntegrator against real production files, implemented
correctly rather than patched later:

- `IBANNumber` uses the sanitised account number — the validator's regex has no
  whitespace stripping, so an IBAN with spaces is rejected outright.
- `AccountID` is reduced to its leading digits; non-numeric codes are reported
  as blocking configuration errors instead of being exported.
- Accounts with no counterpart in the ANAF chart (`899000`, and Odoo core's own
  `999` accounts) are flagged before export rather than rejected after.
- `RegistrationNumber` never carries a trade-register number (`J40/...`); the
  eight ANAF identifier types (00-08) are implemented from the workbook's own
  definition.
- Foreign partners without VAT resolve to type 05/06 with an upper-case country
  code, not to a defaulted `02ro`.
- `<Address>` is emitted whenever city and country are present; the postal code
  is optional, because ANAF's own VAT service returns an empty one for many
  large Romanian companies.
- `<Region>` is emitted only for Romania, formatted `RO-XX`.
- `UOMTableEntry/Description` is always present.
- No element is ever emitted empty — enforced centrally in the XML builder
  rather than per-element.
- `GoodsServicesID` uses `01`/`02`; `ProductCommodityCode` falls back to the
  literal `0` the workbook prescribes when no NC8 code applies.
- `StandardAccountID` reports the statutory account the code maps to, not a
  copy of `AccountID`.

### Known limitations

- Declarations **A** (annual, fixed assets) and **C** (on demand, stock) are not
  produced. Both need data Odoo Community has no source for. The generator
  refuses them explicitly rather than emitting an incomplete file.
- A reporting period with no bank or cash movements produces an empty
  `Payments` section, which DUKIntegrator rejects. Rare in practice; not yet
  handled.
- `MovementTypeTable` is populated only when the Stock app is installed.
- Only the commercial-company statutory chart (`bal_soc_com`) ships. The model
  carries a `chart` column so the IFRS, banking, insurance and NGO charts can be
  added without a schema change.

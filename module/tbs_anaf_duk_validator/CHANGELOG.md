# Changelog — tbs_anaf_duk_validator

All notable changes to this module are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/);
versions track the Odoo `__manifest__.py` `version` string.

> Structure lives in [README.md](./README.md); this file records how the
> module evolved and **why** each change was made. Newest entry on top.

---

## 19.0.1.0.0 — 2026-08-14 — Extraction from l10n_ro_anaf_declarations

### Added
- New standalone module: `anaf.duk.validator` service (`validate()`,
  `generate_pdf()`, `check_installation()`, `get_duk_path()`), moved from
  `l10n_ro_anaf_declarations/models/base/declaration_mixin.py`
  (`_run_dukintegrator()` / `_get_duk_path()` / `DUK_PATH_DEFAULT`)
  verbatim in behavior — same jar lookup order, same subprocess
  invocation, same `errors.txt == "ok"` success check, same 30s timeout.
- `res.config.settings` field `tbs_anaf_duk_path`
  (`tbs_anaf_duk_validator.duk_path` system parameter) + a "Check
  Installation" button, both on **Settings → General Settings → ANAF
  DUKIntegrator**. Previously this path was only settable via Settings →
  Technical → System Parameters (developer mode, no self-serve UI, no way
  to confirm the jar was actually found short of triggering a real
  validation and reading the error).
- License LGPL-3, no price — published free, unlike the source module
  (`l10n_ro_anaf_declarations`, OPL-1/paid). LGPL-3, not AGPL-3: this
  module is a dependency of a proprietary (OPL-1) module, and AGPL-3 would
  contaminate that dependent — LGPL-3 explicitly permits proprietary
  dependents and is the license Odoo core itself ships under.

### Changed
- `l10n_ro_anaf_declarations` now depends on this module; its
  `_run_dukintegrator()` became a thin wrapper delegating to
  `anaf.duk.validator` (see its own CHANGELOG for the full rationale).

> Design note: legacy fallback. `get_duk_path()` checks
> `tbs_anaf_duk_validator.duk_path` first, then falls back to the old
> `l10n_ro_anaf_declarations.duk_path` key, then to the hardcoded default —
> so a production install that already had the old key set keeps working
> through the module split without anyone touching System Parameters by hand.

### Why (business context)
NextERP sells the same DUKIntegrator integration standalone for €5.000
("Romania - ANAF Declaration DUKIntegrator", technical name
`l10n_ro_declaration_duk`), via an HTTP relay to their own hosted service
(`duk.nexterp.ro`). This module runs the jar locally instead — free,
self-hosted, no vendor account, no per-validation cost — and is published
on apps.odoo.com as a lead magnet toward TBS's paid declaration-generation
modules, not as a revenue line on its own.

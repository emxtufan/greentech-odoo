# tbs_anaf_duk_validator

Odoo 19 module that runs Romania's official ANAF **DUKIntegrator** tax
declaration validator (the Java tool ANAF itself uses) against XML you
already generated, and returns a pass/fail verdict plus the confirmation
PDF DUKIntegrator produces on success. It talks to your own, self-hosted
DUKIntegrator install over a local subprocess — no HTTP relay, no vendor
account, no per-request fee.

> Owner: **VICTOR** (business logic, Odoo modeling, and deploy).
> Deploys via TBS's Odoo monorepo (tbs-mod) — see `../DEPLOY.md`.
> Also published standalone on apps.odoo.com (free, LGPL-3), synced from
> this module via `tbs-odoo-apps`.

---

## What it does

Given an XML string and a DUKIntegrator declaration code (`D100`, `D101`,
`D112`, `D205`, `D300`, `D394`), it shells out to the DUKIntegrator jar and
reports back whether ANAF's own validator accepts the XML — the same check
that happens when you upload to SPV, run *before* you upload, so rejections
get caught locally instead of after submission.

| Model | What it is | Why it matters for TBS |
|-------|------------|-------------------------|
| `anaf.duk.validator` | Stateless `AbstractModel` service — `validate()`, `generate_pdf()`, `check_installation()`, `get_duk_path()` | The one place any module calls into DUKIntegrator; nothing else in this module holds state |
| `res.config.settings` (inherited) | Adds `tbs_anaf_duk_path` field + a "Check Installation" button | Lets a client point the module at their DUKIntegrator install from the UI, no server access |

Key features:
- `validate(xml_content, duk_code, year=None, month=None)` → `{success, message}` or `{success: False, errors}`.
- `generate_pdf(xml_content, duk_code, year=None, month=None)` → same, plus `pdf_data` (bytes) on success — DUKIntegrator's own flat, non-editable confirmation PDF.
- `check_installation()` → `{installed, path, jar, message}`, used by the Settings "Check Installation" button so a client can self-verify without reading logs.
- `year`/`month` are optional and only affect dispatch for validators that
  version by period (DUKIntegrator's `an=`/`luna=` CLI params, needed by the
  `AnLunaUI` jar variant); omit them if you don't track a period.

---

## Architecture

```
models/
  anaf_duk_validator.py   — the service: path resolution, jar lookup,
                             subprocess invocation, result parsing
  res_config_settings.py  — Settings field (tbs_anaf_duk_path) + check button
views/
  res_config_settings_views.xml — General Settings page, app block
```

No cron, no controller, no stored model — this module is a thin wrapper
around a `subprocess.run()` call. All state is the one system parameter
(`tbs_anaf_duk_validator.duk_path`).

**Flow:**
```
caller (e.g. l10n_ro_anaf_declarations)
  → self.env['anaf.duk.validator'].validate(xml, 'D300', year=2026, month=7)
      → get_duk_path()            [ir.config_parameter, sudo, global]
      → _find_jar(duk_path)       [DUKIntegrator_AnLunaUI.jar, else DUKIntegrator.jar]
      → java -jar <jar> -v D300 declaration.xml errors.txt 0 [an=2026 luna=7]
      → parse errors.txt ("ok" = success, anything else = error text)
  ← {success, message} / {success: False, errors}
```

---

## Gotchas (read before changing the code)

- **DUKIntegrator itself is not bundled.** ANAF distributes the `.jar`
  files directly (not on Maven/PyPI/npm); this module only knows how to
  invoke them. See [Requirements](#requirements) below for where TBS gets
  them.
- **Two jar variants.** `DUKIntegrator_AnLunaUI.jar` supports the
  `an=`/`luna=` period-dispatch params some newer validators need (e.g.
  D101's versioned namespace); `DUKIntegrator.jar` doesn't. The service
  prefers `AnLunaUI` and only appends `an=`/`luna=` when that's the jar in
  use — passing those params to the plain jar is a silent no-op at best,
  a CLI error at worst.
- **`errors.txt` says `"ok"` on success, not an empty file or exit code 0.**
  DUKIntegrator can exit 0 with real validation errors in the file, or exit
  non-zero on a runtime problem with nothing useful in stdout — the service
  always reads the file and treats anything other than the literal string
  `ok` as a failure, folding in stdout/stderr as extra diagnostics.
- **30-second subprocess timeout.** DUKIntegrator on a cold JVM (`-Xmx128m
  -Xms32m`) is normally sub-second per declaration; a timeout almost always
  means the jar path is wrong (running something that isn't DUKIntegrator)
  or the server is out of memory, not that DUKIntegrator itself is slow.
- **Global, not per-company.** `tbs_anaf_duk_validator.duk_path` is a single
  server filesystem path — DUKIntegrator validates by declaration code, not
  by company, so there's nothing to key per-company here.
- **Legacy parameter fallback.** Installs that had this logic bundled
  inside `l10n_ro_anaf_declarations` (before this module existed) may still
  have `l10n_ro_anaf_declarations.duk_path` set. `get_duk_path()` reads the
  new key first, falls back to the old one, then to the hardcoded default —
  remove that fallback only after confirming no install still relies on it.

---

## Design notes — why it's built this way

Extracted 2026-08-14 from `l10n_ro_anaf_declarations` (a paid TBS module),
where this exact code lived inline in `declaration_mixin.py` as
`_run_dukintegrator()`/`_get_duk_path()`. Two things motivated pulling it
out into its own free module rather than leaving it be:

1. **It's genuinely generic.** Nothing in the DUKIntegrator jar invocation
   depends on how the XML was produced, on `account.move`, or on any
   TBS-specific declaration model — it's XML string + declaration code in,
   verdict out. Bundling it inside a paid, TBS-specific declarations module
   meant nobody else could reuse it without buying that module.
2. **NextERP sells the same integration standalone for €5.000**
   ("Romania - ANAF Declaration DUKIntegrator") — but as an HTTP relay to
   their own hosted infrastructure (`duk.nexterp.ro`), which means a
   recurring dependency on their service and API key. This module instead
   talks to a DUKIntegrator install you run yourself: free, self-hosted,
   no vendor lock-in, no per-validation cost. Publishing it free on
   apps.odoo.com is both the honest thing to do (it's a thin wrapper
   around a government-distributed tool, not novel IP) and a lead magnet
   for TBS's paid declaration-generation modules.

**What did NOT move**, deliberately: `l10n_ro_anaf_declarations` also has a
*second*, older, mostly-unused "DUK" service (`l10n.ro.duk.integrator` in
`models/base/duk_integrator.py`) that does XSD-schema validation with an
optional (never actually wired up) Docker-based DUKIntegrator fallback. It
is a different mechanism, gated by a different company setting
(`l10n_ro_duk_enabled`), used only by the D460 declaration's "Validează"
button — not the jar-based validator six other declaration types call
through their "Validează DUK" buttons. Conflating the two would have been
a bigger, riskier change than the audit finding asked for; it stays where
it is.

---

## Requirements

- Java runtime on the Odoo server (`java` on `PATH`).
- DUKIntegrator `.jar` files, distributed by ANAF as part of its
  declaration-validation tooling (search ANAF's site for "DUKIntegrator", or
  check with your accounting software vendor — most Romanian tools that
  submit to SPV bundle a copy). Not redistributed with this module.
  > TODO: confirm and document the exact current ANAF download URL here —
  > not independently verified at extraction time (2026-08-14), only that
  > TBS's own server already had a working copy in place.
- Place `DUKIntegrator_AnLunaUI.jar` (preferred) or `DUKIntegrator.jar` in
  the folder configured at **Settings → General Settings → ANAF
  DUKIntegrator** (default `/var/odoo/dukintegrator`).

---

## Release history

See [CHANGELOG.md](./CHANGELOG.md).

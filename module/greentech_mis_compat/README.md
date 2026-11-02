# MIS Builder / Odoo 19

OCA's field widget read `props.value`, while Odoo 19 supplies `record` and `name`.
Opening a report directly from a menu produced `Invalid ids list` and an Owl lifecycle error.
This asset patch reads the saved record ID and retains the active-record context fallback.
The widget also receives standard Odoo field props and preserves the record's context.

Installed only in `greentech_financiar_test` (port 8070).
`scripts/financial_fix_demo_reports.py` separately fixes this demo's configuration:

- P&L and actual-versus-budget exclude closing moves so operational profit survives closing.
- Balance-sheet formulas include all asset/liability types, including transfer accounts.
- All three menu actions have an explicit active report context.
- The closing wizard action defaults to the demo's October 2026 period.

No ledger entries are changed by these repairs.

Verification:

- `node scripts/financial_test_mis_widget.mjs`: executes the original OCA component and the
  real Odoo patch implementation with simulated Owl/DOM hooks, against the live HTTP ORM.
  Reproduces the original missing-ID error, then exercises the fixed report IDs, initialization,
  refresh, drilldown, settings and export actions for all three reports.
- `python scripts/financial_audit_demo_reports.py`: current-ledger reconciliation, all report
  drilldown domains, native HTML/XLSX generation, compiled asset delivery and October defaults.
- Results: `logs/mis-widget-regression.json`, `logs/demo-reports-audit.json`.

Visual browser testing was unavailable: Computer Use could not determine the current URL safely.
The PDF engine was still absent; HTML and XLSX exports passed. PDF output is only checked when
the server reports an installed engine.

After installing/updating modules, rerun `financial_fix_demo_reports.py` to restore demo settings.
Configuration snapshot: `logs/demo-reports-before-fix.json`.
Pre-change database backup: `logs/backups/greentech-financiar-test-20261019-132945.zip`.

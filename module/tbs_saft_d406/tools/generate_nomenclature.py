#!/usr/bin/env python3
# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Regenerate the ``tbs_saft_d406`` nomenclature CSVs from the official ANAF workbook.

The only source of truth is the ANAF spreadsheet ``RO_SAFT_SchemaDefCod_<date>.xlsx``
(sheet ``Centralizator_Nomenclatoare`` lists every nomenclature it carries).  Nothing
here is copied from any other Odoo distribution.

Every sheet in that workbook starts with a handful of blank/title rows and some sheets
carry leading blank columns, so the header row is *located by caption* rather than by a
hardcoded index: when ANAF republishes the workbook and shifts rows around, the script
keeps working (and fails loudly if a caption really disappeared).

Usage::

    python3 generate_nomenclature.py                      # regenerate in place
    python3 generate_nomenclature.py --check              # CI gate: diff against repo
    python3 generate_nomenclature.py --workbook X --out Y

Output is deterministic: stable sort order, ``\\n`` line endings, no timestamps inside
the CSV rows.  Provenance (workbook name, SHA-256, generation date, row counts) is
written to a sibling ``PROVENANCE.md`` because Odoo CSV data files cannot carry
comments.
"""

from __future__ import annotations

import argparse
import csv
import filecmp
import hashlib
import logging
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import openpyxl

SCRIPT_VERSION = "1.0.0"

_LOG = logging.getLogger("generate_nomenclature")

MODULE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = MODULE_ROOT.parent
DEFAULT_WORKBOOK = (
    REPO_ROOT / "docs" / "saft-d406" / "docs-xlsx" / "RO_SAFT_SchemaDefCod_16.02.2026.xlsx"
)
DEFAULT_OUT_DIR = MODULE_ROOT / "data" / "nomenclature"
PROVENANCE_FILENAME = "PROVENANCE.md"

# The single statutory chart we ship today.  The `chart` column exists so that the
# other charts in the workbook (IFRS, banks, insurers, ONG, BNR) can be appended later
# without a schema change.
ACCOUNT_CHART = "bal_soc_com"
ACCOUNT_SHEET = "PlanConturiBalSocCom"

# Sheet -> `section` slug for the 6-digit SAF-T TaxCode nomenclature.
TAX_CODE_SECTIONS: dict[str, str] = {
    "Livrari": "livrari",
    "Achizitii ded 100%": "achizitii_ded_100",
    "Achizitii ded 50%": "achizitii_ded_50",
    "Achizitii ded 50%_baserate": "achizitii_ded_50_baserate",
    "Achizitii ded 50%_not_known": "achizitii_ded_50_not_known",
    "Achizitii neded 50%": "achizitii_neded_50",
    "Achizitii neded": "achizitii_neded",
    "Achizitii baserate": "achizitii_baserate",
    "Achizitii not known": "achizitii_not_known",
    "TVA_NoteContabile": "note_contabile",
}

# Several rows carry only a free-text note instead of a Start date column: the Romanian
# VAT change of 2025-08-01 (19% -> 21%, 9% -> 11%) is flagged as "Activ cu 01.08.2025".
ACTIVE_FROM_RX = re.compile(r"activ\s+cu\s+(\d{2})\.(\d{2})\.(\d{4})")
NUMERIC_RATE_RX = re.compile(r"^\d+([.,]\d+)?$")
TAX_CODE_RX = re.compile(r"^\d{6}$")


class NomenclatureError(RuntimeError):
    """Base class for every fatal problem while reading the workbook."""


class MissingSheetError(NomenclatureError):
    pass


class MissingColumnError(NomenclatureError):
    pass


class EmptyTableError(NomenclatureError):
    pass


# --------------------------------------------------------------------------- helpers


def clean(value: object) -> str:
    """Normalise a raw cell value into a stripped, single-spaced string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, int):
        return str(value)
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def norm_caption(text: str) -> str:
    """Lowercase, de-accent and collapse whitespace so captions match across releases."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_marks.replace("\xa0", " ")).strip().lower()


def pad_code(text: str, width: int) -> str:
    """Restore leading zeros lost when Excel stored a code as a number."""
    return text.zfill(width) if text.isdigit() and len(text) < width else text


def parse_date(text: str) -> str:
    """Return an ISO date for the formats ANAF uses, or '' when unparseable."""
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    _LOG.warning("unrecognised date value %r - left empty", text)
    return ""


def slug(text: str) -> str:
    """Sanitise an arbitrary code into a valid, lowercase XML ID fragment."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


class IdAllocator:
    """Hand out unique XML IDs, disambiguating sanitisation collisions with a suffix."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}
        self.collisions: list[str] = []

    def alloc(self, base: str, source_code: str) -> str:
        if base not in self._seen:
            self._seen[base] = source_code
            return base
        for suffix in range(2, 100):
            candidate = f"{base}_{suffix}"
            if candidate not in self._seen:
                self._seen[candidate] = source_code
                self.collisions.append(
                    f"XML ID collision: {source_code!r} and {self._seen[base]!r} both "
                    f"sanitise to {base!r}; used {candidate!r} for {source_code!r}"
                )
                return candidate
        raise NomenclatureError(f"cannot disambiguate XML ID {base!r}")


# ------------------------------------------------------------------------ sheet view


@dataclass(frozen=True)
class SheetView:
    """A worksheet plus the located header row, with caption-based column lookup."""

    name: str
    rows: tuple[tuple[str, ...], ...]
    header: int

    def cell(self, row: Sequence[str], col: int | None) -> str:
        if col is None or col >= len(row):
            return ""
        return row[col]

    def data_rows(self) -> Iterator[tuple[str, ...]]:
        return iter(self.rows[self.header + 1 :])

    def _caption_rows(self, offsets: Sequence[int]) -> Iterator[tuple[str, ...]]:
        for offset in offsets:
            index = self.header + offset
            if 0 <= index < len(self.rows):
                yield self.rows[index]

    def all_cols(
        self,
        pattern: str,
        *,
        exact: bool = False,
        offsets: Sequence[int] = (0,),
        exclude: Iterable[int] = (),
    ) -> list[int]:
        """Every column whose caption matches, searched in `offsets` priority order."""
        regex = re.compile(pattern)
        blocked = set(exclude)
        found: list[int] = []
        for row in self._caption_rows(offsets):
            for col, raw in enumerate(row):
                if col in blocked or not raw or col in found:
                    continue
                caption = norm_caption(raw)
                hit = regex.fullmatch(caption) if exact else regex.search(caption)
                if hit:
                    found.append(col)
            if found:
                break
        return found

    def find_col(self, pattern: str, **kwargs: object) -> int | None:
        cols = self.all_cols(pattern, **kwargs)  # type: ignore[arg-type]
        return cols[0] if cols else None

    def require_col(self, label: str, pattern: str, **kwargs: object) -> int:
        col = self.find_col(pattern, **kwargs)
        if col is None:
            raise MissingColumnError(
                f"sheet {self.name!r}: no column for {label} (pattern {pattern!r}). "
                f"Captions on the header row: {self.captions()}"
            )
        return col

    def optional_col(self, label: str, pattern: str, **kwargs: object) -> int | None:
        col = self.find_col(pattern, **kwargs)
        if col is None:
            _LOG.info("sheet %r: optional column %s not present", self.name, label)
        return col

    def captions(self) -> list[str]:
        return [c for c in self.rows[self.header] if c]


def locate_header(rows: Sequence[Sequence[str]], anchors: Sequence[str], limit: int = 40) -> int:
    """Return the index of the row matching the most expected captions."""
    best_index, best_hits = -1, 0
    for index, row in enumerate(rows[:limit]):
        captions = [norm_caption(cell) for cell in row if cell]
        hits = sum(1 for anchor in anchors if any(anchor in cap for cap in captions))
        if hits > best_hits:
            best_index, best_hits = index, hits
    if best_hits < len(anchors):
        raise MissingColumnError(
            f"header row not found: only {best_hits}/{len(anchors)} expected captions "
            f"matched (anchors: {list(anchors)})"
        )
    return best_index


class WorkbookReader:
    """Lazily materialises the sheets we need as cleaned string matrices."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._wb = openpyxl.load_workbook(path, data_only=True, read_only=True)

    def view(self, sheet_name: str, anchors: Sequence[str]) -> SheetView:
        if sheet_name not in self._wb.sheetnames:
            raise MissingSheetError(
                f"sheet {sheet_name!r} is missing from {self.path.name}; "
                f"available sheets: {self._wb.sheetnames}"
            )
        raw = self._wb[sheet_name]
        rows = tuple(tuple(clean(c) for c in row) for row in raw.iter_rows(values_only=True))
        try:
            header = locate_header(rows, anchors)
        except MissingColumnError as exc:
            raise MissingColumnError(f"sheet {sheet_name!r}: {exc}") from exc
        _LOG.debug("sheet %r: header row = %d (1-based)", sheet_name, header + 1)
        return SheetView(name=sheet_name, rows=rows, header=header)


# ----------------------------------------------------------------------- table model


@dataclass
class Table:
    filename: str
    header: tuple[str, ...]
    rows: list[tuple[str, ...]] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    def sort_and_validate(self) -> None:
        if not self.rows:
            raise EmptyTableError(f"{self.filename}: no data rows extracted - refusing to write")
        self.rows.sort(key=lambda row: row[1])  # column 1 is always `code`


# ------------------------------------------------------------------------ extractors


def extract_tax_types(wb: WorkbookReader) -> Table:
    """`TAX-IMP - Impozite`: the 3-char ANAF tax/impozit nomenclature."""
    sheet = wb.view("TAX-IMP - Impozite", ("cod_imp", "denumire", "tax description"))
    col_code = sheet.require_col("code", r"^cod_imp$", exact=True)
    col_name = sheet.require_col("name", r"^denumire$", exact=True)
    col_name_en = sheet.require_col("name_en", r"tax description")
    col_budget = sheet.require_col("budget_category", r"categorie buget")

    table = Table("l10n.ro.d406.tax.type.csv", ("id", "code", "name", "name_en", "budget_category"))
    ids, seen = IdAllocator(), set()
    for row in sheet.data_rows():
        code = pad_code(sheet.cell(row, col_code), 3)
        if not code:
            continue
        if code in seen:
            table.findings.append(f"duplicate tax type code {code!r} - kept first occurrence")
            continue
        seen.add(code)
        table.rows.append(
            (
                ids.alloc(f"d406_tax_type_{slug(code)}", code),
                code,
                sheet.cell(row, col_name),
                sheet.cell(row, col_name_en),
                sheet.cell(row, col_budget),
            )
        )
    table.findings.extend(ids.collisions)
    return table


@dataclass(frozen=True)
class TaxCodeColumns:
    code: int
    short_code: int | None
    name: int
    name_en: int
    vat_rate: int | None
    date_start: int | None
    date_end: int | None
    inactive: int | None
    note: int | None


def _resolve_tax_code_columns(sheet: SheetView, findings: list[str]) -> TaxCodeColumns:
    """Map the columns of one TVA sheet; captions differ slightly between sheets."""
    # The SAF-T caption sits on the header row (Achizitii*) or one row above (Livrari),
    # where the header row itself only shows the family prefix ("Cod taxa 310").
    code = sheet.require_col("code", r"cod tax.*saf-t", offsets=(0, -1, 1))
    short_code = sheet.optional_col(
        "short_code", r"^cod taxa$", exact=True, offsets=(0,), exclude=(code,)
    )
    columns = TaxCodeColumns(
        code=code,
        short_code=short_code,
        name=sheet.require_col("name", r"descriere cod \(ro\)"),
        name_en=sheet.require_col("name_en", r"code description \(en\)"),
        vat_rate=_resolve_rate_column(sheet, findings),
        date_start=sheet.optional_col("date_start", r"^start date"),
        date_end=sheet.optional_col("date_end", r"^end date"),
        # Sub-header of the activity flag column reads "x - Inactiv".
        inactive=sheet.optional_col("is_active", r"^x\s*-\s*inactiv", offsets=(0, 1, -1)),
        note=sheet.optional_col("note", r"comentarii cod de taxa"),
    )
    if columns.short_code is None:
        findings.append(f"{sheet.name}: no 'Cod taxa' column - short_code left empty")
    if columns.inactive is None:
        findings.append(f"{sheet.name}: no 'x - Inactiv' column - every row treated as active")
    return columns


def _resolve_rate_column(sheet: SheetView, findings: list[str]) -> int | None:
    """Pick the VAT percentage column, never the "Cotă TVA" x-marker matrix."""
    for pattern in (r"^cote\s+tva", r"^cot[ae]\s+tva\s*\(%\)"):
        cols = sheet.all_cols(pattern)
        if len(cols) == 1:
            return cols[0]
        if len(cols) > 1:
            raise MissingColumnError(
                f"sheet {sheet.name!r}: VAT rate caption {pattern!r} is ambiguous "
                f"(columns {cols}) - refusing to guess"
            )
    findings.append(f"{sheet.name}: no VAT rate column found - vat_rate left empty")
    return None


def _tax_code_values(
    sheet: SheetView, row: Sequence[str], cols: TaxCodeColumns, stats: Counter[str]
) -> tuple[str, str, str, str]:
    """Return (vat_rate, date_start, date_end, note) for one TVA row."""
    note = sheet.cell(row, cols.note)
    rate = sheet.cell(row, cols.vat_rate)
    if rate and not NUMERIC_RATE_RX.match(rate):
        # ANAF sometimes puts prose or a -1 placeholder in the rate cell; keep the
        # original text as a note and leave vat_rate empty rather than guess a rate.
        note = " | ".join(filter(None, [note, f"Cota TVA (%): {rate}"]))
        rate = ""
        stats["non_numeric_rate"] += 1
    rate = rate.replace(",", ".")
    date_start = parse_date(sheet.cell(row, cols.date_start))
    date_end = parse_date(sheet.cell(row, cols.date_end))
    match = ACTIVE_FROM_RX.search(norm_caption(note))
    if match and not date_start:
        # "Activ cu 01.08.2025" - the Romanian VAT change to 21% / 11%.
        date_start = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
        stats["date_start_from_note"] += 1
    return rate, date_start, date_end, note


def _tax_code_stats_findings(stats: Counter[str]) -> list[str]:
    findings = []
    if stats["date_start_from_note"]:
        findings.append(
            f"{stats['date_start_from_note']} row(s) had no Start date column value; "
            f"date_start derived from the 'Activ cu dd.mm.yyyy' note"
        )
    if stats["non_numeric_rate"]:
        findings.append(
            f"{stats['non_numeric_rate']} row(s) carried a non-numeric VAT rate; "
            f"vat_rate left empty and the original text kept in note"
        )
    return findings


def _log_sheet_yield(sheet_name: str, kept: int, rejected: Counter[str]) -> None:
    _LOG.info("sheet %-28s -> %4d tax codes", sheet_name, kept)
    if rejected:
        _LOG.info(
            "sheet %r: %d row(s) skipped, code not 6 digits: %s",
            sheet_name, sum(rejected.values()), sorted(rejected),
        )


def extract_tax_codes(wb: WorkbookReader) -> Table:
    """The 6-digit SAF-T TaxCode nomenclature, spread over ten TVA sheets."""
    table = Table(
        "l10n.ro.d406.tax.code.csv",
        (
            "id", "code", "name", "name_en", "short_code", "section",
            "vat_rate", "date_start", "date_end", "is_active", "note",
        ),
    )
    ids, seen, stats = IdAllocator(), {}, Counter()
    anchors = ("descriere cod (ro)", "code description (en)", "cod taxa")
    for sheet_name, section in TAX_CODE_SECTIONS.items():
        sheet = wb.view(sheet_name, anchors)
        cols = _resolve_tax_code_columns(sheet, table.findings)
        before = len(table.rows)
        rejected: Counter[str] = Counter()
        for row in sheet.data_rows():
            # No zero-padding here: SAF-T TaxCodes live in the 3xxxxx family, so Excel
            # cannot have dropped a leading zero. Anything that is not 6 digits is the
            # family-prefix sub-header ("300") or a legend row under the data block.
            code = sheet.cell(row, cols.code)
            if not TAX_CODE_RX.match(code):
                if code:
                    rejected[code] += 1
                continue
            if code in seen:
                table.findings.append(
                    f"duplicate tax code {code!r} in {sheet_name!r} (first seen in "
                    f"{seen[code]!r}) - kept first occurrence"
                )
                continue
            seen[code] = sheet_name
            rate, date_start, date_end, note = _tax_code_values(sheet, row, cols, stats)
            table.rows.append(
                (
                    ids.alloc(f"d406_tax_code_{slug(code)}", code), code,
                    sheet.cell(row, cols.name), sheet.cell(row, cols.name_en),
                    sheet.cell(row, cols.short_code), section, rate, date_start, date_end,
                    "False" if sheet.cell(row, cols.inactive) else "True", note,
                )
            )
        _log_sheet_yield(sheet_name, len(table.rows) - before, rejected)
    table.findings.extend(_tax_code_stats_findings(stats))
    table.findings.extend(ids.collisions)
    return table


def extract_accounts(wb: WorkbookReader) -> Table:
    """`PlanConturiBalSocCom`: the statutory chart of accounts for commercial companies."""
    sheet = wb.view(ACCOUNT_SHEET, ("nr. cont", "descriere [ro]", "descriere [en]"))
    col_code = sheet.require_col("code", r"^nr\. cont$", exact=True)
    col_name = sheet.require_col("name", r"^descriere \[ro\]$", exact=True)
    col_name_en = sheet.require_col("name_en", r"^descriere \[en\]$", exact=True)

    table = Table("l10n.ro.d406.account.csv", ("id", "code", "name", "name_en", "chart"))
    ids, seen = IdAllocator(), set()
    for row in sheet.data_rows():
        code = sheet.cell(row, col_code)
        if not code or not code.isdigit():
            continue  # the English sub-header row and any trailing notes
        if code in seen:
            table.findings.append(f"duplicate account {code!r} - kept first occurrence")
            continue
        seen.add(code)
        xml_id = ids.alloc(f"d406_account_{ACCOUNT_CHART}_{slug(code)}", code)
        table.rows.append(
            (xml_id, code, sheet.cell(row, col_name), sheet.cell(row, col_name_en), ACCOUNT_CHART)
        )
    table.findings.extend(ids.collisions)
    return table


def extract_uom_codes(wb: WorkbookReader) -> Table:
    """`Unitati_masura`: the UN/ECE Rec.20+21 unit list behind UOMTableEntry/Description."""
    sheet = wb.view("Unitati_masura", ("source", "code", "name", "nume"))
    col_code = sheet.require_col("code", r"^code$", exact=True)
    col_name_en = sheet.require_col("name_en", r"^name$", exact=True)
    col_name = sheet.require_col("name", r"^nume$", exact=True)

    table = Table("l10n.ro.d406.uom.code.csv", ("id", "code", "name", "name_en"))
    ids, seen = IdAllocator(), set()
    for row in sheet.data_rows():
        code = sheet.cell(row, col_code)
        if not code:
            continue
        if code in seen:
            table.findings.append(f"duplicate UOM code {code!r} - kept first occurrence")
            continue
        seen.add(code)
        name = sheet.cell(row, col_name)
        name_en = sheet.cell(row, col_name_en)
        # UOMTableEntry/Description is mandatory in the schema, so a unit
        # must always carry a name. ANAF leaves the Romanian column empty
        # for a handful of units; fall back to the English one rather than
        # shipping a row Odoo cannot load.
        if not name:
            name = name_en or code
            table.findings.append(
                f"UOM {code!r} has no Romanian name - fell back to {name!r}"
            )
        table.rows.append(
            (
                ids.alloc(f"d406_uom_{slug(code)}", code),
                code,
                name,
                name_en,
            )
        )
    table.findings.extend(ids.collisions)
    return table


def extract_invoice_types(wb: WorkbookReader) -> Table:
    """`Nom_Tipuri_facturi`: UNTDID 1001 subset with its EN16931 interpretation."""
    sheet = wb.view("Nom_Tipuri_facturi", ("code", "name", "nume", "en16931 interpretation"))
    col_code = sheet.require_col("code", r"^code$", exact=True)
    col_name_en = sheet.require_col("name_en", r"^name$", exact=True)
    col_name = sheet.require_col("name", r"^nume$", exact=True)
    col_en16931 = sheet.require_col("en16931_type", r"^en16931 interpretation$", exact=True)

    table = Table(
        "l10n.ro.d406.invoice.type.csv", ("id", "code", "name", "name_en", "en16931_type")
    )
    ids, seen = IdAllocator(), set()
    for row in sheet.data_rows():
        code = sheet.cell(row, col_code)
        if not code or not code.isdigit():
            continue
        if code in seen:
            table.findings.append(f"duplicate invoice type {code!r} - kept first occurrence")
            continue
        seen.add(code)
        table.rows.append(
            (
                ids.alloc(f"d406_invoice_type_{slug(code)}", code),
                code,
                sheet.cell(row, col_name),
                sheet.cell(row, col_name_en),
                sheet.cell(row, col_en16931),
            )
        )
    table.findings.extend(ids.collisions)
    return table


def extract_payment_methods(wb: WorkbookReader) -> Table:
    """`Nom_Mecanisme_plati`: PaymentMethod codes (many mechanisms map to one method)."""
    sheet = wb.view(
        "Nom_Mecanisme_plati",
        ("code for payment mechanism", "code used for payment method", "metoda de plata"),
    )
    col_mechanism = sheet.require_col("mechanism_code", r"^code for payment mechanism$", exact=True)
    col_code = sheet.require_col("code", r"^code used for payment method$", exact=True)
    col_name = sheet.require_col("name", r"^metoda de plata$", exact=True)
    col_name_en = sheet.require_col("name_en", r"^description for payment method")

    table = Table(
        "l10n.ro.d406.payment.method.csv",
        ("id", "code", "mechanism_code", "name", "name_en"),
    )
    ids, seen, collapsed = IdAllocator(), set(), 0
    for row in sheet.data_rows():
        code = pad_code(sheet.cell(row, col_code), 2)
        if not re.fullmatch(r"\d{2}", code):
            continue  # the Romanian sub-header row repeats the caption in prose
        if code in seen:
            collapsed += 1
            continue
        seen.add(code)
        table.rows.append(
            (
                ids.alloc(f"d406_payment_method_{slug(code)}", code),
                code,
                sheet.cell(row, col_mechanism),
                sheet.cell(row, col_name),
                sheet.cell(row, col_name_en),
            )
        )
    if collapsed:
        table.findings.append(
            f"{collapsed} PaymentMechanism rows collapsed into {len(table.rows)} distinct "
            f"PaymentMethod codes (first mechanism kept per code)"
        )
    table.findings.extend(ids.collisions)
    return table


EXTRACTORS = (
    extract_tax_types,
    extract_tax_codes,
    extract_accounts,
    extract_uom_codes,
    extract_invoice_types,
    extract_payment_methods,
)


# ---------------------------------------------------------------------------- output


def build_tables(workbook: Path) -> list[Table]:
    if not workbook.is_file():
        raise NomenclatureError(f"workbook not found: {workbook}")
    reader = WorkbookReader(workbook)
    tables: list[Table] = []
    for extractor in EXTRACTORS:
        table = extractor(reader)
        table.sort_and_validate()
        tables.append(table)
    return tables


def write_csv(path: Path, table: Table) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(table.header)
        writer.writerows(table.rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_provenance(path: Path, workbook: Path, tables: Sequence[Table]) -> None:
    lines = [
        "# Nomenclature provenance",
        "",
        "Generated by `tools/generate_nomenclature.py` - do not edit the CSVs by hand.",
        "Odoo CSV data files cannot carry comments, so provenance lives here.",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Source workbook | `{workbook.name}` |",
        f"| SHA-256 | `{sha256(workbook)}` |",
        f"| Generated (UTC) | {datetime.now(timezone.utc).date().isoformat()} |",
        f"| Script version | {SCRIPT_VERSION} |",
        "",
        "## Row counts",
        "",
        "| File | Data rows |",
        "| --- | ---: |",
    ]
    lines += [f"| `{t.filename}` | {len(t.rows)} |" for t in tables]
    findings = [(t.filename, f) for t in tables for f in t.findings]
    lines += ["", "## Findings", ""]
    lines += [f"- `{name}`: {text}" for name, text in findings] or ["- none"]
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def generate(workbook: Path, out_dir: Path) -> list[Table]:
    tables = build_tables(workbook)
    out_dir.mkdir(parents=True, exist_ok=True)
    for table in tables:
        write_csv(out_dir / table.filename, table)
    write_provenance(out_dir / PROVENANCE_FILENAME, workbook, tables)
    return tables


def print_summary(tables: Sequence[Table], out_dir: Path, *, title: str = "written to") -> None:
    width = max(len(t.filename) for t in tables)
    print(f"\nNomenclature {title} {out_dir}")
    print(f"{'file'.ljust(width)}  {'rows':>6}")
    print(f"{'-' * width}  {'-' * 6}")
    for table in tables:
        print(f"{table.filename.ljust(width)}  {len(table.rows):>6}")
    print(f"{'TOTAL'.ljust(width)}  {sum(len(t.rows) for t in tables):>6}")
    findings = [(t.filename, f) for t in tables for f in t.findings]
    if findings:
        print(f"\n{len(findings)} finding(s):")
        for name, text in findings:
            print(f"  - {name}: {text}")


def run_check(workbook: Path, out_dir: Path) -> int:
    """Regenerate into a temp dir and diff against the committed CSVs."""
    with tempfile.TemporaryDirectory(prefix="d406-nomenclature-") as tmp:
        tmp_dir = Path(tmp)
        tables = generate(workbook, tmp_dir)
        differences: list[str] = []
        for table in tables:
            committed = out_dir / table.filename
            if not committed.is_file():
                differences.append(f"{table.filename}: missing from {out_dir}")
            elif not filecmp.cmp(committed, tmp_dir / table.filename, shallow=False):
                differences.append(f"{table.filename}: differs from the generated output")
        if not (out_dir / PROVENANCE_FILENAME).is_file():
            differences.append(f"{PROVENANCE_FILENAME}: missing from {out_dir}")
        print_summary(tables, tmp_dir, title="regenerated (dry run) into")
    if differences:
        print("\nCHECK FAILED - regenerate with `python3 generate_nomenclature.py`:")
        for line in differences:
            print(f"  - {line}")
        return 1
    print("\nCHECK OK - committed CSVs match the workbook.")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate the tbs_saft_d406 nomenclature CSVs from the ANAF workbook.",
    )
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK, help="source .xlsx")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate into a temp dir and fail if the committed CSVs differ",
    )
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    parser.add_argument("--version", action="version", version=SCRIPT_VERSION)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)-8s %(message)s",
        stream=sys.stderr,
    )
    workbook, out_dir = args.workbook.resolve(), args.out.resolve()
    try:
        if args.check:
            return run_check(workbook, out_dir)
        print_summary(generate(workbook, out_dir), out_dir)
    except NomenclatureError as exc:
        _LOG.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

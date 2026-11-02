# Copyright 2026 Greentech Professionals
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Stream ANAF history without a platform-specific grep subprocess."""


def matching_rows(path, vat_numbers):
    wanted = set(vat_numbers)
    with open(path, encoding="utf-8-sig") as stream:
        for number, raw in enumerate(stream, 1):
            row = raw.strip().split("#")
            if len(row) < 2 or row[1] not in wanted:
                continue
            if len(row) < 7 or not row[0].isdigit():
                raise ValueError(f"Malformed ANAF history record at line {number}")
            yield row[:7]

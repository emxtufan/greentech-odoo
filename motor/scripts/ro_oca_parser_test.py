"""Regression tests for Windows ANAF parsing (synthetic records only)."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "anaf_history",
    ROOT / "third_party_addons/oca-ro-19/l10n_ro_vat_on_payment/anaf_history.py",
)
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


class HistoryTests(unittest.TestCase):
    def rows(self, text, numbers):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
            path = Path(folder) / "registry.txt"
            path.write_text(text, encoding="utf-8-sig")
            return list(parser.matching_rows(path, numbers))

    def test_exact_cif_and_crlf(self):
        result = self.rows(
            "1#123#20260101##20260101#20260101#I\r\n"
            "2#1234#20260101##20260101#20260101#I\r\n", ["123"]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], "123")
        self.assertEqual(result[0][3], "")

    def test_empty_or_no_match(self):
        self.assertEqual(self.rows("\n", ["123"]), [])
        self.assertEqual(self.rows("1#124#20260101##20260101#20260101#I\n", ["123"]), [])

    def test_invalid_relevant_record_fails(self):
        with self.assertRaises(ValueError):
            self.rows("1#123#incomplete\n", ["123"])

    def test_all_historical_operations_retained(self):
        rows = self.rows(
            "1#123#20260101##20260101#20260101#I\n"
            "2#123#20260101#20260301#20260301#20260301#D\n",
            ["123"],
        )
        self.assertEqual([r[6] for r in rows], ["I", "D"])


if __name__ == "__main__":
    unittest.main()

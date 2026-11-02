"""Executable non-fiscal regression tests; all identifiers/amounts are synthetic."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "custom_addons/greentech_anaf_d112"
sys.path.insert(0, str(ADDON))
from services import document, duk

spec = importlib.util.spec_from_file_location("d112_fixtures", ADDON / "tests/fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class TestDocument(unittest.TestCase):
    def test_minimal_structure_valid(self):
        _, errors = document.validate(fixtures.minimal(document), "RO12345674", 2026, 9)
        self.assertEqual(errors, [])

    def test_person_structure_and_roundtrip(self):
        payload = fixtures.with_person(document)
        raw, errors = document.validate(payload, "12345674", 2026, 9)
        self.assertEqual(errors, [])
        self.assertEqual(document.from_xml(raw), payload)
        self.assertTrue(document.semantic_equal(raw, document.to_xml(document.from_xml(raw))))

    def test_new_document_never_invents_salary_values(self):
        data = document.new_document(2026, 9, {"cif": "12345674"})
        self.assertNotIn("totalPlata_A", data["children"][0]["attrs"])
        _, errors = document.validate(data, "12345674", 2026, 9)
        self.assertTrue(errors)

    def test_unknown_data_cannot_disappear(self):
        data = fixtures.minimal(document)
        data["children"][0]["attrs"]["unknown_fiscal_amount"] = "123"
        with self.assertRaises(ValueError):
            document.to_xml(data)

    def test_no_numeric_coercion(self):
        data = fixtures.minimal(document)
        data["children"][0]["attrs"]["totalPlata_A"] = 0
        with self.assertRaises(ValueError):
            document.normalize(data)

    def test_company_and_period(self):
        data = fixtures.minimal(document)
        self.assertTrue(document.validate(data, "87654321", 2026, 9)[1])
        self.assertTrue(document.validate(data, "12345674", 2026, 8)[1])
        with self.assertRaises(ValueError):
            document.period_check(2026, 6)
        with self.assertRaises(ValueError):
            document.period_check(2027, 1)

    def test_namespace_xxe_and_text_rejected(self):
        raw = document.to_xml(fixtures.minimal(document))
        for bad in [raw.replace(document.NS.encode(), b"wrong:namespace"),
                    b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]>' + raw,
                    raw.replace(b"</angajator>", b"</angajator>unhandled text")]:
            with self.assertRaises(ValueError):
                document.from_xml(bad)

    def test_escaping_and_strings(self):
        data = fixtures.minimal(document)
        data["children"][0]["attrs"]["den"] = 'TEST & CO <FICTIV> "ȘȚ"'
        self.assertEqual(document.from_xml(document.to_xml(data)), data)

    def test_duplicate_person(self):
        data = fixtures.with_person(document)
        data["children"].append(deepcopy(data["children"][1]))
        self.assertTrue(any("CNP" in e for e in document.validate(data, "12345674", 2026, 9)[1]))

    def test_sequence_is_preserved_and_invalid_order_rejected(self):
        data = fixtures.minimal(document)
        data["children"][0]["children"].reverse()
        self.assertEqual(document.from_xml(document.to_xml(data)), data)
        self.assertTrue(document.validate(data, "12345674", 2026, 9)[1])

    def test_optional_sections_lossless(self):
        data = fixtures.with_person(document)
        employer = data["children"][0]
        for tag in ("angajatorC1", "angajatorC2", "angajatorD", "angajatorF1", "angajatorF2"):
            node = document.empty_node(tag)
            definition = document.editor_schema()["types"][document.editor_schema()["tags"][tag]]
            for attr in definition["attributes"]:
                node["attrs"][attr["name"]] = (attr.get("enumeration") or [attr.get("minInclusive", "0")])[0]
            employer["children"].append(node)
        raw = document.to_xml(data)
        self.assertEqual(document.from_xml(raw), data)


class TestDuk(unittest.TestCase):
    def test_report_contract(self):
        for report, expected in [("ok\n", "valid"), ("E: error", "invalid"), ("F: failed", "invalid"),
                                 ("W: warning", "warnings"), ("", "unknown"), ("done", "unknown")]:
            self.assertEqual(duk.report_status(report), expected)

    def test_unavailable_never_runs(self):
        with patch.object(duk, "readiness", return_value=("", ["Missing Java"])), patch.object(duk.subprocess, "run") as run:
            self.assertEqual(duk.run(b"test", "")["status"], "unavailable")
            run.assert_not_called()

    def test_zero_exit_without_report_does_not_validate(self):
        with patch.object(duk, "readiness", return_value=("java", [])), patch.object(
                duk.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"ok", b"")):
            self.assertEqual(duk.run(b"test", str(ROOT))["status"], "invalid")

    def test_hash_pinning_detects_modified_validator(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hashes = {}
            for rel in duk.REQUIRED:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"TEST ONLY")
                hashes[rel] = document.fingerprint(path.read_bytes())
            (root / "runtime-lock.json").write_text(json.dumps({"files": hashes}))
            java = root / "java.exe"
            java.write_bytes(b"NO EXECUTION")
            self.assertEqual(duk.readiness(folder, str(java))[1], [])
            config = root / "config/config.properties"
            config.unlink()
            self.assertIn("config/config.properties", "\n".join(duk.readiness(folder, str(java))[1]))
            config.write_bytes(b"TEST ONLY")
            (root / "lib/D112Validator.jar").write_bytes(b"CHANGED")
            self.assertTrue(duk.readiness(folder, str(java))[1])

    def test_success_without_pdf_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "runtime-lock.json").write_text('{"files":{}}')
            def fake(command, **kwargs):
                Path(command[8]).write_text("ok")
                return subprocess.CompletedProcess(command, 0, b"", b"")
            with patch.object(duk, "readiness", return_value=("java", [])), patch.object(duk.subprocess, "run", side_effect=fake):
                result = duk.run(document.to_xml(fixtures.minimal(document)), folder, make_pdf=True)
                self.assertEqual(result["status"], "invalid")
                self.assertIsNone(result["pdf"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

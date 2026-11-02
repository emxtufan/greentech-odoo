import base64
from copy import deepcopy
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged, new_test_user

from ..services import document
from .fixtures import minimal


@tagged("post_install", "-at_install")
class TestDeclaration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].with_context(no_vat_validation=True).create({
            "name": "D112 SOFTWARE TEST", "vat": "12345674",
        })
        cls.user = new_test_user(cls.env(context=dict(cls.env.context, no_reset_password=True)), login="d112_software_tester",
                                groups="base.group_user,greentech_anaf_d112.group_anaf",
                                company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.Model = cls.env["gt.anaf.d112"].with_user(cls.user).with_context(allowed_company_ids=cls.company.ids)

    def record(self, payload=True):
        return self.Model.create({"company_id": self.company.id, "year": 2026, "month": "9",
                                  "payload": minimal(document) if payload else {}})

    def test_schema_only_does_not_mark_fiscal_valid(self):
        record = self.record()
        record.action_validate_schema()
        self.assertEqual(record.state, "xsd")
        self.assertTrue(record.xml_output)
        self.assertFalse(record.validated_hash)
        with self.assertRaises(UserError):
            record.action_generate_pdf()

    def test_forging_results_denied(self):
        record = self.record()
        for field, value in [("state", "valid"), ("xml_output", b"ZmFrZQ=="), ("audit_log", "fake")]:
            with self.assertRaises(AccessError):
                record.write({field: value})
        with self.assertRaises(AccessError):
            self.Model.create({"state": "valid", "year": 2026, "month": "9"})

    def test_changed_payload_invalidates_all_outputs(self):
        record = self.record()
        with patch("odoo.addons.greentech_anaf_d112.services.duk.run",
                   return_value={"status": "valid", "report": "ok", "runtime": {"MOCK": "SOFTWARE TEST"}}):
            record.action_validate_anaf()
        self.assertEqual(record.state, "valid")
        self.assertTrue(record.validated_hash)
        data = deepcopy(record.payload)
        data["attrs"]["functie_declar"] = "MODIFICAT"
        record.write({"payload": data})
        self.assertEqual(record.state, "draft")
        self.assertFalse(record.validated_hash)
        self.assertFalse(record.xml_output)
        self.assertFalse(record.pdf_output)

    def test_import_roundtrip(self):
        record = self.record(False)
        source = document.to_xml(minimal(document))
        record.write({"upload": base64.b64encode(source), "upload_filename": "TEST.xml"})
        record.action_import()
        self.assertTrue(document.semantic_equal(source, document.to_xml(record.payload)))
        self.assertEqual(record.source_hash, document.fingerprint(source))
        self.assertEqual(record.state, "draft")
        self.assertFalse(record.upload)

    def test_wrong_company_import_rejected(self):
        record = self.record(False)
        source = document.to_xml(minimal(document, "87654321"))
        record.write({"upload": base64.b64encode(source)})
        with self.assertRaises(UserError):
            record.action_import()
        self.assertFalse(record.payload)

    def test_filing_locks_edits_and_revision_starts_unvalidated(self):
        record = self.record()
        record.write({"filing_index": "TEST_ONLY"})
        with self.assertRaises(UserError):
            record.write({"year": 2027})
        action = record.action_revision()
        revision = self.Model.browse(action["res_id"])
        self.assertEqual(revision.revision, 2)
        self.assertEqual(revision.state, "draft")
        self.assertFalse(revision.filing_index)
        self.assertEqual(revision.payload, record.payload)

    def test_multi_company_and_nonmember_access(self):
        record = self.record()
        outsider = new_test_user(self.env(context=dict(self.env.context, no_reset_password=True)), login="d112_unprivileged", groups="base.group_user",
                                company_id=self.company.id, company_ids=[Command.set(self.company.ids)])
        with self.assertRaises(AccessError):
            record.with_user(outsider).read(["payload"])
        with self.assertRaises(AccessError):
            self.Model.with_user(outsider).editor_schema()
        other = self.env["res.company"].create({"name": "D112 OTHER COMPANY"})
        hidden = self.env["gt.anaf.d112"].create({"company_id": other.id, "year": 2026, "month": "9"})
        with self.assertRaises(AccessError):
            hidden.with_user(self.user).with_context(allowed_company_ids=self.company.ids).read(["payload"])

    def test_missing_runtime_never_succeeds(self):
        record = self.record()
        with patch("odoo.addons.greentech_anaf_d112.services.duk.readiness",
                   return_value=("", ["Java indisponibil TEST"])):
            record.action_validate_anaf()
        self.assertEqual(record.state, "xsd")
        self.assertFalse(record.validated_hash)

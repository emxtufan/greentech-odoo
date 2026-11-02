import base64
from unittest.mock import patch
from lxml import etree
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged, new_test_user
from odoo.addons.greentech_ro_vat_journals.tests.test_journals import TestVatJournals
from ..services import calculation as c, runtime


@tagged("post_install", "-at_install")
class TestD300(TestVatJournals):
    """The journal regression cases are inherited deliberately: D300 uses its source."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({"vat": "RO12345674", "street": "Strada Demonstrativa 1", "city": "Bucuresti"})
        cls.env["gt.d300.mapping"].seed_standard(cls.company)

    def declaration(self, **kw):
        return self.env["gt.anaf.d300"].create({
            "company_id": self.company.id, "year": 2026, "month": 9, "period_type": "L",
            "vat_registered": True, "balances_reviewed": True, "special_reviewed": True,
            "signer_last": "TEST", "signer_first": "DEMO", "signer_role": "Administrator",
            "caen": "6201", "bank_name": "Banca Demo", "bank_account": "RO49AAAA1B31007593840000", **kw})

    def values(self, d):
        d.action_calculate()
        return {r["code"]: r for r in d.data["rows"]}

    def test_d300_standard_and_rounding(self):
        self.invoice("sale", base=1000.49)
        self.invoice("sale", base=1000.49)
        self.invoice("purchase", base=500)
        d = self.declaration()
        v = self.values(d)
        self.assertEqual((v["9"]["base"], v["19"]["tax"], v["31"]["tax"], v["44"]["tax"]), (2001, 420, 105, 315))
        self.assertEqual(d.data["errors"], [])
        d.action_xml()
        root = etree.fromstring(base64.b64decode(d.xml_file))
        self.assertEqual(root.tag, "{%s}declaratie300" % c.NS)
        self.assertEqual(root.get("R17_2"), "420")
        self.assertEqual(root.get("R41_2"), "315")
        self.assertEqual(d.state, "xml")
        self.assertFalse(d.validated_at)

    def test_d300_negative_refunds(self):
        self.invoice("sale", base=500, refund=True)
        d = self.declaration()
        v = self.values(d)
        self.assertEqual((v["9"]["base"], v["19"]["tax"], v["45"]["tax"]), (-500, -105, 105))

    def test_d300_cash_period_and_pending(self):
        for kind in ("sale", "purchase"):
            m = self.invoice(kind, cash=True, date="2026-08-10")
            self.pay(m, 605, "2026-09-15")
            self.pay(m, 605, "2026-10-15")
        d = self.declaration()
        v = self.values(d)
        self.assertEqual((v["9"]["base"], v["24"]["base"], v["19"]["tax"], v["31"]["tax"]), (500, 500, 105, 105))
        self.assertEqual(d.data["info"]["tva_a"], 105)
        self.assertEqual(d.data["info"]["tva_b"], 105)
        self.assertEqual(d.data["errors"], [])

    def test_d300_nd_then_prorata(self):
        self.invoice("purchase", deduction=50)
        mapping = self.env["gt.d300.mapping"].search([("tax_id", "=", self.taxes["purchase", False].id), ("kind", "=", "purchase")])
        mapping.prorata = True
        d = self.declaration(prorata=80)
        v = self.values(d)
        self.assertEqual((v["24"]["tax"], v["30"]["tax"], v["31"]["tax"]), (210, 210, 84))

    def test_d300_missing_tax_blocks(self):
        m = self.invoice()
        m.button_draft()
        m.invoice_line_ids.tax_ids = False
        m.action_post()
        d = self.declaration()
        self.values(d)
        self.assertEqual(d.state, "blocked")
        self.assertTrue(any("încadrare" in s for s in d.data["errors"]))
        with self.assertRaises(UserError):
            d.action_xml()

    def test_d300_missing_mapping_blocks(self):
        self.invoice()
        self.env["gt.d300.mapping"].search([("company_id", "=", self.company.id)]).unlink()
        d = self.declaration()
        self.values(d)
        self.assertEqual(d.state, "blocked")

    def test_d300_changes_invalidate_and_external_changes_detected(self):
        m = self.invoice("sale")
        d = self.declaration()
        self.values(d)
        d.action_xml()
        m.ref = "Sursa modificata"
        with self.assertRaises(UserError):
            d.action_xml()
        self.values(d)
        d.month = 10
        self.assertFalse(d.data)
        self.assertFalse(d.xml_file)
        self.assertEqual(d.state, "draft")

    def test_d300_payload_state_protected(self):
        d = self.declaration()
        for values in ({"state": "valid"}, {"data": {}}, {"validated_hash": "fake"}, {"pdf_file": "fake"}):
            with self.assertRaises(AccessError):
                d.write(values)
        with self.assertRaises(AccessError):
            self.env["gt.anaf.d300"].create({"company_id": self.company.id, "state": "valid"})
        bypass = self.env["gt.anaf.d300"].with_context(default_state="valid", default_pdf_file="fake").create({
            "company_id": self.company.id})
        self.assertEqual(bypass.state, "draft")
        self.assertFalse(bypass.pdf_file)

    def test_d300_carry_adjustments_revision(self):
        self.invoice("sale", base=1000)
        d = self.declaration()
        self.env["gt.d300.adjustment"].create({"declaration_id": d.id, "row_code": "41",
            "tax": 500, "reason": "Sold negativ nesolicitat", "evidence": "Decont precedent"})
        v = self.values(d)
        self.assertEqual(v["45"]["tax"], 290)
        d.action_xml()
        d.adjustment_ids.tax = 600
        self.assertFalse(d.xml_file)
        v = self.values(d)
        self.assertEqual(v["45"]["tax"], 390)
        result = d.action_revision()
        rev = self.env["gt.anaf.d300"].browse(result["res_id"])
        self.assertEqual(rev.previous_id, d)
        self.assertEqual(len(rev.adjustment_ids), 1)
        self.assertFalse(rev.data)

    def test_d300_bad_period_and_refund(self):
        d = self.declaration(month=4, period_type="T")
        with self.assertRaises(UserError):
            d.action_calculate()
        d.write({"month": 8})
        self.assertEqual(str(d.date_from), "2026-07-01")
        self.assertEqual(str(d.date_to), "2026-08-31")
        d.refund = True
        self.values(d)
        self.assertTrue(any("5.000" in e for e in d.data["errors"]))
        with self.assertRaises(ValueError):
            c.period(2025, 12, "L")

    def test_d300_reverse_charge_totals_no_double(self):
        # Valid source contribution pairs: child is counted once in parent/total.
        items = [{"row": r, "base": 1000, "tax": 210, "eligible": 105} for r in ("5.1", "20.1")]
        v, attrs = c.calculate(items, [], 100)
        self.assertEqual((v["5"]["base"], v["19"]["tax"], v["30"]["tax"], v["31"]["tax"]), (1000, 210, 210, 105))
        self.assertEqual(v["44"]["tax"], 105)
        self.assertEqual(attrs["R18_1_2"], 210)

    def test_d300_reverse_charge_missing_pair(self):
        d = self.declaration()
        self.env["gt.d300.adjustment"].create({"declaration_id": d.id, "row_code": "5.1",
            "base": 1000, "tax": 210, "reason": "Test", "evidence": "Document test"})
        self.values(d)
        self.assertTrue(any("Taxare inversă" in s for s in d.data["errors"]))

    def test_d300_actual_reverse_charge(self):
        reverse = self.env["account.tax"].search([("company_id", "=", self.company.id),
            ("name", "=", "21% R"), ("type_tax_use", "=", "purchase")], limit=1)
        inv = self.invoice()
        inv.button_draft()
        inv.invoice_line_ids.tax_ids = reverse
        inv.action_post()
        for kind, row in (("sale", "12.1"), ("purchase", "26.1")):
            self.env["gt.d300.mapping"].create({"company_id": self.company.id, "tax_id": reverse.id,
                "kind": kind, "row_code": row, "note": "Taxare inversa interna"})
        d = self.declaration()
        v = self.values(d)
        self.assertEqual((v["12"]["tax"], v["26"]["tax"], v["19"]["tax"], v["31"]["tax"], v["44"]["tax"]), (210, 210, 210, 210, 0))
        self.assertEqual(d.data["errors"], [])

    def test_d300_all_input_rows_xml_and_exemption(self):
        for code, label in c.INPUT_ROWS:
            definition = c.BY_ROW[code]
            item = {"row": code, "base": 100 if definition[2] else 0,
                    "tax": 21 if definition[3] else 0, "eligible": 21}
            values, attrs = c.calculate([item], [], 100)
            if definition[2]:
                self.assertEqual(attrs[definition[2]], 100)
            if definition[3]:
                self.assertEqual(attrs[definition[3]], 21)
        v, _ = c.calculate([{"row": "29.1", "base": 1000, "tax": 0, "eligible": 0}], [], 100)
        self.assertEqual(v["29"]["base"], 1000)
        self.assertEqual(v["30"]["base"], 0)

    def test_d300_manual_adjustments_both_balances_blocked(self):
        d = self.declaration()
        for row in ("38", "41"):
            self.env["gt.d300.adjustment"].create({"declaration_id": d.id, "row_code": row,
                "tax": 100, "reason": "Test", "evidence": "Decont"})
        self.values(d)
        self.assertTrue(any("simultan" in e for e in d.data["errors"]))

    def test_d300_deduction_on_cash_basis(self):
        inv = self.invoice("purchase", cash=True, deduction=50)
        self.pay(inv, 605, "2026-09-20")
        d = self.declaration()
        v = self.values(d)
        self.assertEqual((v["24"]["base"], v["24"]["tax"], v["31"]["tax"]), (500, 105, 53))
        self.assertEqual(d.data["errors"], [])

    def test_d300_checksum_includes_only_required_info(self):
        _, attrs = c.calculate([], [], 100, {"nr_facturi": 2, "baza": 100, "tva": 21,
                                            "valoare_a": 1000, "tva_a": 210, "total_curent": 500})
        self.assertEqual(attrs["totalPlata_A"], 123)
        number = c.payment_reference(2026, 12, "T")
        self.assertEqual(len(number), 23)
        self.assertEqual(number[-2:], f"{sum(map(int,number[:21]))%100:02d}")

    def test_d300_security_other_company(self):
        d = self.declaration()
        other = self.env["res.company"].create({"name": "D300 other company"})
        user = new_test_user(self.env, login="d300-only-other", groups="account.group_account_user",
                            company_id=other.id)
        user.company_ids = other
        with self.assertRaises(AccessError):
            d.with_user(user).with_context(allowed_company_ids=other.ids).action_calculate()

    def test_d300_no_false_validator_success(self):
        self.assertTrue(runtime.readiness("", "")[1])
        r = runtime.run(b"<x/>", "", "", make_pdf=True)
        self.assertEqual(r["status"], "unavailable")
        self.assertIsNone(r["pdf"])

    def test_d300_download_xml_preserves_official_validation(self):
        self.invoice("sale")
        d = self.declaration()
        self.values(d)
        with patch.object(runtime, "run", return_value={"status": "valid", "report": "ok", "pdf": None}):
            d.action_validate()
        before = (d.state, d.validated_hash, d.validated_at, d.xml_file)
        action = d.action_xml()
        self.assertEqual((d.state, d.validated_hash, d.validated_at, d.xml_file), before)
        self.assertNotIn("NEVALIDAT", action["url"])

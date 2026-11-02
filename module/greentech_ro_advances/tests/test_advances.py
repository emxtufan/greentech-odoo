import base64
from io import BytesIO
from pypdf import PdfReader
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged, new_test_user
from odoo.addons.greentech_anaf_d300.tests.test_d300 import TestD300


@tagged("post_install", "-at_install")
class TestAdvances(TestD300):
    """Run the complete journals/D300 regressions as well as the advance circuit."""

    def advance(self, kind="sale", amount=1000, cash=False, date="2026-09-10"):
        account = self.env["account.account"].search([
            ("company_ids", "in", self.company.id),
            ("code", "=like", "419%" if kind == "sale" else "4092%")], limit=1)
        wizard = self.env["gt.advance.create"].create({
            "company_id": self.company.id, "kind": kind, "partner_id": self.partner.id,
            "date": date, "ref": "TEST AVANS",
            "line_ids": [Command.create({"name": "Avans servicii", "account_id": account.id,
                "amount": amount, "tax_ids": [Command.set(self.taxes[kind, cash].ids)]})]})
        move = self.env["account.move"].browse(wizard.action_create()["res_id"])
        move.action_post()
        return move

    def final(self, kind="sale", amount=2500, cash=False, date="2026-09-20"):
        move = self.invoice(kind, base=amount, cash=cash, date=date)
        move.button_draft()
        return move

    def allocate(self, source, final, amount):
        line = source.invoice_line_ids.filtered(lambda l: l._gt_is_source())[:1]
        w = self.env["gt.advance.allocate"].create({
            "move_id": final.id, "source_id": line.id, "amount": amount})
        w.action_apply()
        return final.invoice_line_ids.filtered("gt_advance_origin_id")[-1]

    def test_advance_partial_full_and_d300(self):
        for kind in ("sale", "purchase"):
            a = self.advance(kind)
            self.pay(a, 1210, "2026-09-12")
            f1 = self.final(kind, amount=800)
            self.allocate(a, f1, 400)
            self.assertEqual((a.gt_advance_reserved, a.gt_advance_remaining), (400, 600))
            f1.action_post()
            self.assertEqual((a.gt_advance_used, a.gt_advance_remaining), (400, 600))
            f2 = self.final(kind, amount=1700)
            self.allocate(a, f2, 600)
            f2.action_post()
            self.assertEqual((a.gt_advance_used, a.gt_advance_remaining), (1000, 0))
            totals = self.journal(kind).data["totals"]
            self.assertEqual((totals["base"], totals["vat"]), (2500, 525))
            report = self.env["gt.advance.report"].create({
                "company_id": self.company.id, "kind": kind,
                "date_from": "2026-09-01", "date_to": "2026-09-30"})
            report.action_refresh()
            self.assertEqual(report.data["totals"]["closing"], 0)
            self.assertEqual(len(report.data["details"]), 3)
        d = self.declaration()
        v = self.values(d)
        self.assertEqual((v["19"]["tax"], v["31"]["tax"]), (525, 525))
        self.assertEqual(d.data["errors"], [])
        d.action_xml()

    def test_advance_reservation_overuse_cancel(self):
        a = self.advance()
        f = self.final()
        self.allocate(a, f, 700)
        f2 = self.final()
        with self.assertRaises(UserError):
            self.allocate(a, f2, 400)
        f.button_cancel()
        self.assertEqual(a.gt_advance_remaining, 1000)
        self.allocate(a, f2, 1000)
        f2.action_post()
        with self.assertRaises(UserError):
            a.button_draft()

    def test_advance_refunds_restore_and_source_refund(self):
        a = self.advance()
        f = self.final()
        self.allocate(a, f, 600)
        f.action_post()
        refund = f._reverse_moves([{"date": "2026-09-25", "invoice_date": "2026-09-25"}])
        self.assertEqual(a.gt_advance_remaining, 400)
        refund.action_post()
        self.assertEqual(a.gt_advance_remaining, 1000)
        source_refund = a._reverse_moves([{"date": "2026-09-26", "invoice_date": "2026-09-26"}])
        source_refund.action_post()
        self.assertEqual(a.gt_advance_remaining, 0)

    def test_advance_source_refund_cannot_double_consume(self):
        a = self.advance()
        f = self.final()
        self.allocate(a, f, 600)
        f.action_post()
        refund = a._reverse_moves([{"date": "2026-09-25", "invoice_date": "2026-09-25"}])
        with self.assertRaises(UserError):
            refund.action_post()

    def test_advance_tax_included_and_discount(self):
        a = self.advance()
        a.button_draft()
        tax = self.taxes["sale", False].copy({"name": "TEST AVANS TVA INCLUS 21",
                                           "price_include_override": "tax_included"})
        line = a.invoice_line_ids
        line.write({"price_unit": 1210, "discount": 10, "tax_ids": [Command.set(tax.ids)]})
        a.action_post()
        self.assertAlmostEqual(a.amount_untaxed, 900)
        f = self.final()
        reduction = self.allocate(a, f, 450)
        self.assertAlmostEqual(reduction.price_subtotal, -450)
        self.assertAlmostEqual(reduction.price_total, -544.5)
        f.action_post()
        self.assertAlmostEqual(a.gt_advance_remaining, 450)

    def test_advance_direct_rpc_wrong_partner_tax_overuse(self):
        a = self.advance()
        f = self.final()
        line = self.allocate(a, f, 600)
        line.quantity = -2
        with self.assertRaises(UserError):
            f.action_post()
        line.quantity = -.6
        f.partner_id = self.partner_b
        with self.assertRaises(UserError):
            f.action_post()
        f.partner_id = self.partner
        line.tax_ids = False
        with self.assertRaises(UserError):
            f.action_post()

    def test_advance_cash_basis_across_periods(self):
        for kind in ("sale", "purchase"):
            a = self.advance(kind, cash=True, date="2026-08-10")
            self.pay(a, 1210, "2026-08-12")
            f = self.final(kind, amount=2500, cash=True)
            self.allocate(a, f, 1000)
            f.action_post()
            self.pay(f, 1815, "2026-09-22")
            totals = self.journal(kind).data["totals"]
            self.assertEqual((totals["base"], totals["eligible"]), (1500, 315))
        d = self.declaration()
        v = self.values(d)
        self.assertEqual((v["19"]["tax"], v["31"]["tax"]), (315, 315))

    def test_advance_historical_report_exports(self):
        a = self.advance(date="2026-08-10")
        f = self.final()
        self.allocate(a, f, 400)
        f.action_post()
        late = self.final(date="2026-10-10")
        self.allocate(a, late, 600)
        late.action_post()
        r = self.env["gt.advance.report"].create({
            "company_id": self.company.id, "date_from": "2026-09-01", "date_to": "2026-09-30"})
        r.action_refresh()
        self.assertEqual(r.data["totals"], {"opening": 1000, "debit": 0, "credit": -400, "closing": 600})
        r.action_csv()
        self.assertIn("TOTAL;;1000.00;0.00;-400.00;600.00", base64.b64decode(r.export_file).decode("utf-8-sig"))
        r.action_pdf()
        pdf = PdfReader(BytesIO(base64.b64decode(r.export_file)))
        self.assertIn("600.00", "\n".join(p.extract_text() for p in pdf.pages))
        with self.assertRaises(AccessError):
            r.data = {}

    def test_advance_source_protected_and_foreign_blocked(self):
        a = self.advance()
        f = self.final()
        self.allocate(a, f, 100)
        with self.assertRaises(UserError):
            a.invoice_line_ids.price_unit = 2000
        with self.assertRaises(UserError):
            a.partner_id = self.partner_b
        with self.assertRaises(UserError):
            a.button_cancel()

    def test_advance_multicompany_access(self):
        a = self.advance()
        outsider = self.env["res.company"].create({"name": "Altă firmă avansuri"})
        user = new_test_user(self.env, login="advance_other",
                            groups="account.group_account_user",
                            company_id=outsider.id, company_ids=[Command.set(outsider.ids)])
        model = self.env["gt.advance.report"].with_user(user).with_context(allowed_company_ids=outsider.ids)
        with self.assertRaises(AccessError):
            model.create({"company_id": self.company.id})
        with self.assertRaises(AccessError):
            a.with_user(user).with_context(allowed_company_ids=outsider.ids).read(["gt_advance_remaining"])

    def test_advance_duplicate_final_cannot_bypass(self):
        a = self.advance()
        f = self.final()
        self.allocate(a, f, 600)
        f.action_post()
        duplicate = f.copy()
        with self.assertRaises(UserError):
            duplicate.action_post()

    def test_advance_native_sale_order(self):
        self.env.user.sudo().write({"group_ids": [Command.link(self.env.ref("sales_team.group_sale_manager").id)]})
        product = self.env["product.product"].create({
            "name": "TEST SERVICIU AVANS", "type": "service", "invoice_policy": "order",
            "list_price": 2500, "taxes_id": [Command.set(self.taxes["sale", False].ids)],
            "property_account_income_id": self.company_data["default_account_revenue"].id})
        order = self.env["sale.order"].create({
            "company_id": self.company.id, "partner_id": self.partner.id,
            "order_line": [Command.create({"product_id": product.id, "product_uom_qty": 1})]})
        order.action_confirm()
        w = self.env["sale.advance.payment.inv"].create({
            "sale_order_ids": [Command.set(order.ids)], "advance_payment_method": "percentage", "amount": 40})
        a = w._create_invoices(order)
        a.write({"invoice_date": "2026-09-10", "date": "2026-09-10"})
        self.assertTrue(a.invoice_line_ids.account_id.code.startswith("419"))
        a.action_post()
        final = order._create_invoices(final=True)
        final.write({"invoice_date": "2026-09-20", "date": "2026-09-20"})
        final.action_post()
        self.assertEqual(a.gt_advance_remaining, 0)
        self.assertEqual(final.amount_total, 1815)

    def test_advance_foreign_and_earlier_date_blocked(self):
        a = self.advance()
        early = self.final(date="2026-09-01")
        with self.assertRaises(UserError):
            self.allocate(a, early, 100)
        a.button_draft()
        self.env.ref("base.EUR").sudo().active = True
        a.currency_id = self.env.ref("base.EUR")
        a.action_post()
        f = self.final()
        f.currency_id = a.currency_id
        with self.assertRaises(UserError):
            self.allocate(a, f, 100)

    def test_advance_refund_cannot_release_twice(self):
        a = self.advance()
        f = self.final()
        self.allocate(a, f, 400)
        f.action_post()
        refund = f._reverse_moves([{"date": "2026-09-25", "invoice_date": "2026-09-25"}])
        refund.action_post()
        f2 = self.final()
        self.allocate(a, f2, 800)
        f2.action_post()
        again = f._reverse_moves([{"date": "2026-09-26", "invoice_date": "2026-09-26"}])
        with self.assertRaises(UserError):
            again.action_post()

    def test_advance_wizard_double_click_idempotent(self):
        a = self.advance()
        f = self.final()
        wizard = self.env["gt.advance.allocate"].create({
            "move_id": f.id, "source_id": a.invoice_line_ids.id, "amount": 300})
        wizard.action_apply()
        wizard.action_apply()
        self.assertEqual(a.gt_advance_reserved, 300)

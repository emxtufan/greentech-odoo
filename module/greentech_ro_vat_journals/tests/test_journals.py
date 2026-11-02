import base64
from io import BytesIO
from pypdf import PdfReader
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged, new_test_user
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestVatJournals(AccountTestInvoicingCommon):
    country_code = "RO"
    chart_template = "ro"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        cls.company.currency_id = cls.env.ref("base.RON")
        cls.company.tax_exigibility = True
        cls.partner = cls.env["res.partner"].create({"name": "TEST JURNALE TVA"})
        cls.taxes = {}
        for kind in ("purchase", "sale"):
            for cash in (False, True):
                cls.taxes[kind, cash] = cls.env["account.tax"].search([
                    ("company_id", "=", cls.company.id), ("type_tax_use", "=", kind),
                    ("amount", "=", 21), ("amount_type", "=", "percent"),
                    ("tax_exigibility", "=", "on_payment" if cash else "on_invoice"),
                ], order="id", limit=1)
                assert cls.taxes[kind, cash], (kind, cash)
        cls.bank = cls.company_data["default_journal_bank"]
        cls.company.l10n_ro_nondeductible_account_id = cls.company_data["default_account_expense"]
        for tax in [cls.taxes["purchase", False], cls.taxes["purchase", True]]:
            for rep in tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids:
                if not rep.tag_ids:
                    tag = cls.env["account.account.tag"].create({
                        "name": f"TEST VAT {tax.id} {rep.id}", "applicability": "taxes",
                        "country_id": cls.env.ref("base.ro").id})
                    rep.tag_ids = [Command.set(tag.ids)]
                for tag in rep.tag_ids:
                    if not tag.l10n_ro_nondeductible_tag_id:
                        tag.l10n_ro_nondeductible_tag_id = tag.copy({"name": tag.name + " ND test"})

    def invoice(self, kind="purchase", base=1000, cash=False, date="2026-09-10", refund=False, deduction=100):
        account = self.company_data["default_account_expense" if kind == "purchase" else "default_account_revenue"]
        move = self.env["account.move"].create({
            "company_id": self.company.id, "partner_id": self.partner.id,
            "move_type": ("in" if kind == "purchase" else "out") + ("_refund" if refund else "_invoice"),
            "invoice_date": date, "date": date, "ref": "DEMO TEST JURNAL",
            "invoice_line_ids": [Command.create({
                "name": "Serviciu test", "account_id": account.id, "quantity": 1, "price_unit": base,
                "tax_ids": [Command.set(self.taxes[kind, cash].ids)], "deductible_amount": deduction,
            })],
        })
        move.action_post()
        return move

    def journal(self, kind="purchase", start="2026-09-01", end="2026-09-30", **kw):
        record = self.env["gt.ro.vat.journal"].create({
            "company_id": self.company.id, "kind": kind, "date_from": start, "date_to": end, **kw})
        record.action_refresh()
        return record

    def pay(self, invoice, amount, date):
        term = invoice.line_ids.filtered(lambda l: l.account_id.account_type in (
            "liability_payable", "asset_receivable"))[:1]
        sign = -1 if term.balance > 0 else 1
        payment = self.env["account.move"].create({
            "company_id": self.company.id, "journal_id": self.bank.id, "date": date,
            "line_ids": [Command.create({
                "name": "Plată test", "account_id": term.account_id.id, "partner_id": self.partner.id,
                "debit": max(sign * amount, 0), "credit": max(-sign * amount, 0),
            }), Command.create({
                "name": "Bancă test", "account_id": self.bank.default_account_id.id,
                "debit": max(-sign * amount, 0), "credit": max(sign * amount, 0),
            })]})
        payment.action_post()
        (term | payment.line_ids.filtered(lambda l: l.account_id == term.account_id)).reconcile()
        return payment

    def test_purchase_and_sale(self):
        for kind in ("purchase", "sale"):
            self.invoice(kind)
            totals = self.journal(kind).data["totals"]
            self.assertEqual((totals["base"], totals["vat"], totals["eligible"]), (1000, 210, 210))

    def test_refunds_negative(self):
        for kind in ("purchase", "sale"):
            self.invoice(kind, refund=True)
            total = self.journal(kind).data["totals"]
            self.assertEqual((total["base"], total["vat"]), (-1000, -210))

    def test_partial_payment_historical_cutoff(self):
        for kind in ("purchase", "sale"):
            inv = self.invoice(kind, cash=True, date="2026-08-10")
            self.pay(inv, 605, "2026-09-15")
            self.pay(inv, 605, "2026-10-15")
            total = self.journal(kind).data["totals"]
            self.assertEqual((total["base"], total["vat"], total["paid"], total["unpaid"]), (1000, 210, 605, 605))
            self.assertEqual((total["paid_base"], total["pending_base"], total["pending_vat"]), (500, 500, 105))
            self.assertEqual(total["eligible"], 105)

    def test_fully_paid_before_period_not_included(self):
        inv = self.invoice(cash=True, date="2026-07-10")
        self.pay(inv, 1210, "2026-08-15")
        self.assertFalse(self.journal().data["rows"])

    def test_prior_unpaid_invoice_carried_forward(self):
        self.invoice(cash=True, date="2026-07-10")
        total = self.journal().data["totals"]
        self.assertEqual((total["pending_base"], total["pending_vat"], total["eligible"]), (1000, 210, 0))

    def test_nondeductible_50_and_100(self):
        inv = self.invoice(deduction=50)
        self.invoice(deduction=0)
        total = self.journal().data["totals"]
        self.assertEqual((total["base"], total["vat"], total["eligible"], total["nondeductible"]),
                         (2000, 420, 105, 315),
                         [(l.account_id.code, l.balance, l.display_type, l.name, l.tax_line_id.id,
                           l.l10n_ro_non_deductible_line_id.id) for l in inv.line_ids])
        filtered = self.journal(deduction="50").data["totals"]
        self.assertEqual((filtered["base"], filtered["vat"], filtered["eligible"]), (1000, 210, 105))

    def test_nondeductible_cash_basis(self):
        inv = self.invoice(cash=True, deduction=50)
        self.pay(inv, 605, "2026-09-20")
        total = self.journal().data["totals"]
        self.assertEqual((total["eligible"], total["nondeductible"], total["pending_vat"]), (52.5, 52.5, 105),
                         (self.company.l10n_ro_accounting, self.taxes["purchase",True].l10n_ro_is_nondeductible,
                          [(l.account_id.code,l.balance,l.display_type,l.tax_line_id.id) for l in inv.tax_cash_basis_created_move_ids.line_ids]))

    def test_mixed_deductibility_same_invoice_cash_filter(self):
        inv = self.invoice(cash=True, deduction=50)
        inv.button_draft()
        inv.write({"invoice_line_ids": [Command.create({
            "name": "Linie integral deductibilă", "account_id": self.company_data["default_account_expense"].id,
            "quantity": 1, "price_unit": 1000, "deductible_amount": 100,
            "tax_ids": [Command.set(self.taxes["purchase", True].ids)]})]})
        inv.action_post()
        self.pay(inv, 1210, "2026-09-20")
        total = self.journal(deduction="50").data["totals"]
        self.assertEqual((total["base"], total["vat"], total["eligible"], total["nondeductible"]),
                         (1000, 210, 52.5, 52.5))

    def test_draft_and_other_period_excluded(self):
        inv = self.invoice()
        inv.button_draft()
        self.invoice(date="2026-08-10")
        self.assertFalse(self.journal().data["rows"])

    def test_zero_tax_classification_and_partner_filter(self):
        inv = self.invoice()
        inv.button_draft()
        inv.invoice_line_ids.tax_ids = False
        inv.action_post()
        data = self.journal().data
        self.assertEqual(data["totals"]["base"], 1000)
        self.assertEqual(data["totals"]["vat"], 0)
        self.assertTrue(data["warnings"])
        self.assertFalse(self.journal(partner_id=self.partner_b.id).data["rows"])

    def test_manual_note_base_and_explicit_exclusion(self):
        vat_account = self.taxes["purchase", False].invoice_repartition_line_ids.filtered(
            lambda l: l.repartition_type == "tax").account_id[:1]
        expense = self.company_data["default_account_expense"]
        entry = self.env["account.move"].create({
            "date": "2026-09-10", "journal_id": self.company_data["default_journal_misc"].id,
            "line_ids": [Command.create({"account_id": vat_account.id, "debit": 21, "gt_vat_manual_base": 100}),
                         Command.create({"account_id": expense.id, "credit": 21})]})
        entry.action_post()
        data = self.journal().data
        self.assertEqual((data["totals"]["base"], data["totals"]["vat"]), (100, 21))
        entry.line_ids.filtered(lambda l: l.account_id == vat_account).gt_vat_journal_exclude = True
        data = self.journal().data
        self.assertEqual(data["excluded_notes"], 1)
        self.assertFalse(data["rows"])

    def test_snapshots_protected_and_invalidated(self):
        self.invoice()
        journal = self.journal()
        with self.assertRaises(AccessError):
            journal.write({"data": {"totals": {"vat": 0}}})
        journal.date_to = "2026-10-31"
        self.assertFalse(journal.data)

    def test_multiple_rates_and_reverse_charge(self):
        inv = self.invoice()
        inv.button_draft()
        tax11 = self.taxes["purchase", False].copy({"name": "TEST 11%", "amount": 11})
        inv.write({"invoice_line_ids": [Command.create({
            "name": "Cota a doua", "account_id": self.company_data["default_account_expense"].id,
            "quantity": 1, "price_unit": 100, "tax_ids": [Command.set(tax11.ids)]})]})
        inv.action_post()
        data = self.journal().data
        self.assertEqual((data["totals"]["base"], data["totals"]["vat"]), (1100, 221))
        self.assertEqual(len(data["rows"]), 2)
        reverse = self.env["account.tax"].search([
            ("company_id", "=", self.company.id), ("name", "=", "21% R"),
            ("type_tax_use", "=", "purchase")], limit=1)
        self.assertTrue(reverse)
        inv2 = self.invoice()
        inv2.button_draft()
        inv2.invoice_line_ids.tax_ids = reverse
        inv2.action_post()
        self.assertEqual(self.journal("sale").data["totals"]["vat"], 210)
        self.assertEqual(self.journal().data["totals"]["vat"], 431)

    def test_foreign_currency_uses_posted_ron(self):
        eur = self.env.ref("base.EUR")
        eur.active = True
        self.env["res.currency.rate"].create({
            "company_id": self.company.id, "currency_id": eur.id, "name": "2026-09-01", "rate": 0.2})
        inv = self.invoice(base=100)
        inv.button_draft()
        inv.currency_id = eur
        inv.action_post()
        total = self.journal().data["totals"]
        self.assertAlmostEqual(total["base"], 500, places=2)
        self.assertAlmostEqual(total["vat"], 105, places=2)

    def test_company_scope_and_csv(self):
        self.invoice()
        journal = self.journal()
        journal.action_csv()
        csv = base64.b64decode(journal.export_file).decode("utf-8-sig")
        self.assertIn("210,00", csv)
        self.assertIn("TOTAL", csv)
        journal.action_pdf()
        pdf = PdfReader(BytesIO(base64.b64decode(journal.pdf_file)))
        text = "\n".join(page.extract_text() for page in pdf.pages)
        self.assertIn("210,00", text)
        self.assertIn("Jurnal cumpărări", text)
        other = self.env["res.company"].create({"name": "TEST AUTRE FIRME"})
        user = new_test_user(self.env, login="vat_journal_scope", groups="account.group_account_user",
            company_id=other.id, company_ids=[Command.set(other.ids)])
        with self.assertRaises(AccessError):
            journal.with_user(user).with_context(allowed_company_ids=other.ids).action_refresh()

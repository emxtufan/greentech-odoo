from unittest.mock import patch
from types import SimpleNamespace

from lxml import etree
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.addons.tbs_saft_d406.tests.test_d406_export import TestD406Export
from odoo.addons.l10n_ro_edi_stock_extension.tests.test_etransport_value import TestEtransportValue
from odoo.addons.greentech_tbs_integration.models import duk
from odoo.addons.l10n_ro_edi_stock_extension.models.etransport_api_extra import ETransportAPIExtra


@tagged("post_install", "-at_install")
class TestIntegration(TestD406Export):
    def test_period_and_segmentation_are_guarded(self):
        wizard = self._generate()
        for vals in ({"date_to": "2026-03-30"}, {"total_segments": 2},
                     {"declaration_type": "T"}):
            with self.cr.savepoint():
                wizard.write(vals)
                with self.assertRaises(UserError):
                    wizard.action_generate()
                # Roll back the setting for the next independent case.
                wizard.write({"date_to": "2026-03-31", "total_segments": 1, "declaration_type": "L"})

    def test_output_fields_cannot_be_forged(self):
        wizard = self._generate()
        for vals in ({"gt_duk_valid": True}, {"attachment_id": False},
                     {"validation_log": "ok"}, {"state": "done"}):
            with self.assertRaises(AccessError):
                wizard.write(vals)
        with self.assertRaises(AccessError):
            self.env[wizard._name].create({"gt_duk_valid": True})

    def test_source_changes_prevent_stale_download(self):
        wizard = self._generate()
        self.partner_ro.write({"city": "Brasov"})
        with self.assertRaisesRegex(UserError, "schimbat"):
            wizard.action_download()

    def test_options_clear_previous_artifacts(self):
        wizard = self._generate()
        wizard.write({"gt_contact_last": "Alt nume"})
        self.assertFalse(wizard.attachment_id)
        self.assertFalse(wizard.gt_duk_valid)
        self.assertEqual(wizard.state, "draft")

    def test_missing_used_tax_mapping_is_blocked(self):
        wizard = self._generate()
        tax = self.env["account.tax"].with_company(self.company).search([
            ("company_id", "=", self.company.id), ("l10n_ro_d406_tax_code_id", "!=", False)], limit=1)
        tax.l10n_ro_d406_tax_code_id = False
        with self.assertRaisesRegex(UserError, "încadrare SAF-T"):
            wizard.action_generate()

    def test_missing_partner_address_does_not_become_company_address(self):
        wizard = self._generate()
        self.partner_ro.city = False
        with self.assertRaisesRegex(UserError, "partenerilor"):
            wizard.action_generate()

    def test_wrong_company_is_blocked_before_raw_sql(self):
        wizard = self._generate()
        other = self.env["res.company"].search([("id", "!=", self.company.id)], limit=1)
        with self.assertRaises(AccessError):
            wizard.with_context(allowed_company_ids=[other.id]).action_generate()

    def test_duk_rejects_doctype_without_launching_java(self):
        with patch.object(duk.subprocess, "run") as run:
            result = self.env["anaf.duk.validator"].validate(
                '<!DOCTYPE x [<!ENTITY a SYSTEM "file:///secret">]><x>&a;</x>',
                "D406", year=2026, month=3)
            self.assertFalse(result["success"])
            run.assert_not_called()

    def test_duk_nonzero_exit_and_missing_pdf_are_not_success(self):
        raw = '<AuditFile><Header><HeaderComment>L</HeaderComment></Header></AuditFile>'
        def fake(cmd, **kwargs):
            error_path = duk.Path(cmd[cmd.index("D406") + 2])
            error_path.write_text("ok", encoding="utf-8")
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"failure")
        with patch.object(duk.subprocess, "run", side_effect=fake):
            result = self.env["anaf.duk.validator"].validate(raw, "D406", year=2026, month=3)
            self.assertFalse(result["success"])
        def no_pdf(cmd, **kwargs):
            duk.Path(cmd[cmd.index("D406") + 2]).write_text("ok", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout=b"GT_D406_ANAF_VALID", stderr=b"")
        with patch.object(duk.subprocess, "run", side_effect=no_pdf):
            result = self.env["anaf.duk.validator"].generate_pdf(raw, "D406", year=2026, month=3)
            self.assertFalse(result["success"])

    def test_advance_negative_line_reduces_tax_total(self):
        move = self.env["account.move"].with_company(self.company).search([
            ("company_id", "=", self.company.id), ("move_type", "=", "out_invoice")], limit=1)
        move.button_draft()
        line = move.invoice_line_ids[0]
        move.write({"invoice_line_ids": [Command.create({
            "name": "Regularizare avans demonstrativ", "account_id": line.account_id.id,
            "quantity": 1, "price_unit": -100, "tax_ids": [Command.set(line.tax_ids.ids)],
        })]})
        move.action_post()
        wizard = self._generate()
        tree = etree.fromstring(wizard.attachment_id.raw)
        invoice = tree.find(".//{*}SalesInvoices/{*}Invoice")
        totals = invoice.find("{*}InvoiceDocumentTotals")
        self.assertAlmostEqual(float(totals.find("{*}TaxInformationTotals/{*}TaxBase").text), 900)
        self.assertAlmostEqual(float(totals.find("{*}TaxInformationTotals/{*}TaxAmount/{*}Amount").text), 189)


@tagged("post_install", "-at_install")
class TestTransportIntegration(TestEtransportValue):
    def test_list_responses_without_upload_status_are_supported(self):
        company = SimpleNamespace(vat="RO12345674", l10n_ro_edi_access_token="test-only",
                                  l10n_ro_edi_test_env=True)
        for payload in ([], {"mesaje": []}, {"inregistrari": [{"uit": "TEST"}]}):
            response = SimpleNamespace(status_code=200, json=lambda: payload)
            client = SimpleNamespace(request=lambda **kw: response)
            self.assertEqual(ETransportAPIExtra().get_list(company, session=client)["content"], payload)
        client = SimpleNamespace(request=lambda **kw: SimpleNamespace(status_code=503))
        self.assertIn("error", ETransportAPIExtra().get_list(company, session=client))

    def test_context_defaults_cannot_forge_validation(self):
        wizard = self.env["l10n.ro.d406.export.wizard"].with_context(default_gt_duk_valid=True).create({})
        self.assertFalse(wizard.gt_duk_valid)
    def test_declared_pack_price_and_quantity_have_same_unit(self):
        picking = self._picking()
        pack = self.env["uom.uom"].create({
            "name": "Pachet 10 test", "relative_uom_id": self.product.uom_id.id, "relative_factor": 10})
        picking.move_ids.product_uom = pack
        self.assertAlmostEqual(self._value(picking, "20"), 1000)
        self.assertEqual(picking._l10n_ro_edi_stock_get_qty_and_uom(picking.move_ids)[0], 5)

    def test_tariff_code_can_be_configured_without_enterprise(self):
        self.product.gt_etransport_nc = "85044095"
        picking = self._picking()
        self.assertEqual(picking._l10n_ro_edi_stock_get_codtarifar(self.product), "85044095")
        with self.assertRaises(ValidationError):
            self.product.gt_etransport_nc = "ABCD"

    def test_sale_discount_and_included_vat_are_removed(self):
        tax = self.env["account.tax"].create({
            "name": "TVA inclus test", "amount": 21, "price_include_override": "tax_included",
            "company_id": self.company.id, "type_tax_use": "sale"})
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id, "company_id": self.company.id,
            "order_line": [Command.create({
                "product_id": self.product.id, "product_uom_qty": 5, "price_unit": 121,
                "discount": 10, "tax_ids": [Command.set(tax.ids)],
            })]})
        picking = self._picking()
        picking.move_ids.sale_line_id = order.order_line
        self.assertAlmostEqual(self._value(picking, "20"), 90)
    def test_net_and_gross_weight_odoo19(self):
        self.product.weight = 2.5
        picking = self._picking()
        self.assertEqual(picking._l10n_ro_edi_stock_compute_net_weight(picking.move_ids), 12.5)
        self.assertEqual(picking._l10n_ro_edi_stock_compute_gross_weight(picking.move_ids), 12.5)

    def test_document_requires_one_owner(self):
        with self.assertRaises(ValidationError):
            self.env["l10n.ro.edi.stock.document.line"].create({"document_date": "2026-10-01"})

    def test_document_has_transfer_company(self):
        picking = self._picking()
        row = self.env["l10n.ro.edi.stock.document.line"].create({
            "picking_id": picking.id, "document_date": "2026-10-01"})
        self.assertEqual(row.company_id, picking.company_id)

    def test_company_guard_precedes_anaf_call(self):
        other = self.env["res.company"].search([("id", "!=", self.company.id)], limit=1)
        for model in ("l10n.ro.edi.stock.list.wizard", "l10n.ro.edi.stock.transporter.info.wizard"):
            values = {"company_id": other.id}
            if "operator_vat" in self.env[model]._fields:
                values["operator_vat"] = "RO12345674"
            wizard = self.env[model].create(values).with_context(allowed_company_ids=[self.company.id])
            with self.assertRaises(AccessError):
                wizard.action_fetch()

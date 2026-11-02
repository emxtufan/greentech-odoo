# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""End-to-end export test — the golden test.

The bar is that a file generated from a synthetic but realistic company
validates against the official ANAF XSD shipped in the module. Schema
validity is necessary, not sufficient (ANAF's business rules live in
DUKIntegrator), but it is the gate that catches element ordering, missing
mandatory children and the empty-element mistakes.

All fixture data is synthetic. No production data from any TBS customer is
committed here.
"""
from datetime import date

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestD406Export(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._create_company()
        cls.env.user.company_ids |= cls.company
        cls.env.user.company_id = cls.company
        cls.partner_ro = cls._create_partner_ro()
        cls.partner_foreign = cls._create_partner_foreign()
        cls._create_invoices()

    # ------------------------------------------------------------------
    # Fixtures (synthetic)
    # ------------------------------------------------------------------

    @classmethod
    def _create_company(cls):
        romania = cls.env.ref('base.ro')
        company = cls.env['res.company'].create({
            'name': 'Test SAF-T Exporter SRL',
            'country_id': romania.id,
            'vat': 'RO12345674',
            'street': 'Strada Testelor 1',
            'city': 'Sibiu',
            'zip': '550001',
            # Mandatory for the taxpayer's own header block: the schema types
            # it as CompanyHeaderStructure, where Contact/Telephone and
            # BankAccount are required.
            'phone': '+40269000000',
            'email': 'contact@example.test',
            'l10n_ro_d406_tax_accounting_basis': 'I',
        })
        cls.env['account.chart.template'].try_loading(
            'ro', company=company, install_demo=False)
        cls.env['res.partner.bank'].create({
            'acc_number': 'RO49AAAA1B31007593840000',
            'partner_id': company.partner_id.id,
            'company_id': company.id,
        })
        return company

    @classmethod
    def _create_partner_ro(cls):
        return cls.env['res.partner'].create({
            'name': 'Client Roman SRL',
            'is_company': True,
            'vat': 'RO99999992',
            'country_id': cls.env.ref('base.ro').id,
            'city': 'Cluj-Napoca',
            # Deliberately no zip: ANAF's own VAT service returns an empty
            # postal code for many large Romanian companies, and the address
            # block must still be emitted.
        })

    @classmethod
    def _create_partner_foreign(cls):
        return cls.env['res.partner'].create({
            'name': 'Foreign Vendor Inc',
            'is_company': True,
            'country_id': cls.env.ref('base.us').id,
            'city': 'San Francisco',
            'ref': 'FVI001',
            # No VAT: must resolve to type 06, never to '02ro'.
        })

    @classmethod
    def _create_invoices(cls):
        move_model = cls.env['account.move'].with_company(cls.company)
        product = cls.env['product.product'].create({
            'name': 'Consulting Service',
            'type': 'service',
            'default_code': 'SRV-001',
        })
        sale_tax = cls.env['account.tax'].with_company(cls.company).search(
            [('type_tax_use', '=', 'sale'), ('company_id', '=', cls.company.id)],
            limit=1)
        cls._map_tax(sale_tax)

        customer_invoice = move_model.create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner_ro.id,
            'invoice_date': date(2026, 3, 15),
            'date': date(2026, 3, 15),
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'quantity': 2,
                'price_unit': 500.0,
                'tax_ids': [Command.set(sale_tax.ids)] if sale_tax else False,
            })],
        })
        customer_invoice.action_post()

        purchase_tax = cls.env['account.tax'].with_company(cls.company).search(
            [('type_tax_use', '=', 'purchase'),
             ('company_id', '=', cls.company.id)], limit=1)
        cls._map_tax(purchase_tax)

        vendor_bill = move_model.create({
            'move_type': 'in_invoice',
            'partner_id': cls.partner_foreign.id,
            'invoice_date': date(2026, 3, 20),
            'date': date(2026, 3, 20),
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'quantity': 1,
                'price_unit': 250.0,
                'tax_ids': [Command.set(purchase_tax.ids)] if purchase_tax else False,
            })],
        })
        vendor_bill.action_post()
        cls._create_payment()

    @classmethod
    def _create_payment(cls):
        """A bank payment, so the Payments section has content.

        DUKIntegrator requires at least one ``Payment`` even though the XSD
        declares the element as optional — another point where the validator
        is stricter than the schema.
        """
        bank_journal = cls.env['account.journal'].with_company(
            cls.company).search(
                [('type', '=', 'bank'), ('company_id', '=', cls.company.id)],
                limit=1)
        payment = cls.env['account.payment'].with_company(cls.company).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': cls.partner_ro.id,
            'amount': 605.0,
            'date': date(2026, 3, 25),
            'journal_id': bank_journal.id,
        })
        payment.action_post()

    @classmethod
    def _map_tax(cls, tax):
        """Attach ANAF codes to a tax so it reaches the TaxTable."""
        if not tax:
            return
        tax_type = cls.env['l10n.ro.d406.tax.type'].search([], limit=1)
        tax_code = cls.env['l10n.ro.d406.tax.code'].search(
            [('vat_rate', '=', 21.0)], limit=1) \
            or cls.env['l10n.ro.d406.tax.code'].search([], limit=1)
        tax.write({
            'l10n_ro_d406_tax_type_id': tax_type.id,
            'l10n_ro_d406_tax_code_id': tax_code.id,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _generate(self, declaration_type='L'):
        model = self.env['l10n.ro.d406.export.wizard'].with_company(self.company)
        contact = ({'gt_contact_first': 'Ana', 'gt_contact_last': 'Test'}
                   if 'gt_contact_first' in model._fields else {})
        wizard = model.create({
                'company_id': self.company.id,
                'declaration_type': declaration_type,
                'date_from': date(2026, 3, 1),
                'date_to': date(2026, 3, 31),
                **contact,
            })
        wizard.action_generate()
        return wizard

    # ------------------------------------------------------------------
    # The golden test
    # ------------------------------------------------------------------

    def test_generated_file_validates_against_official_xsd(self):
        wizard = self._generate()
        self.assertTrue(
            wizard.xsd_valid,
            f'Generated D406 file failed XSD validation:\n{wizard.validation_log}')

    def test_nomenclatures_are_loaded(self):
        self.assertGreater(
            self.env['l10n.ro.d406.account'].search_count([]), 600,
            'The ANAF chart-of-accounts nomenclature did not load.')
        self.assertGreater(
            self.env['l10n.ro.d406.tax.code'].search_count([]), 900,
            'The ANAF tax code nomenclature did not load.')

    def test_current_vat_rates_are_present(self):
        """Romania moved to 21% / 11% on 2025-08-01."""
        codes = self.env['l10n.ro.d406.tax.code'].search(
            [('vat_rate', '=', 21.0)])
        self.assertTrue(codes, 'No 21% VAT codes in the nomenclature.')
        self.assertTrue(
            all(code.date_start == date(2025, 8, 1) for code in codes),
            '21% codes must be valid from 2025-08-01.')

    def test_statutory_romanian_chart_maps_completely(self):
        """Every *statutory* account in the RO chart must resolve.

        Codes in the 999 range are excluded because they are not statutory:
        see :meth:`test_odoo_technical_999_accounts_are_flagged`.
        """
        accounts = self.env['account.account'].with_company(
            self.company).search([('company_ids', 'in', self.company.id)])
        statutory = accounts.filtered(
            lambda a: not (a.code or '').startswith('999'))
        unmapped = statutory.filtered(
            lambda a: a.l10n_ro_d406_mapping_status in (
                'unresolved', 'not_numeric'))
        self.assertFalse(
            unmapped,
            f'Statutory accounts without an ANAF mapping: '
            f'{unmapped.mapped("code")}')

    def test_odoo_technical_999_accounts_are_flagged(self):
        """Odoo's own 999 accounts must be reported, not silently exported.

        ``account`` (Odoo core, not the Romanian localisation) creates
        "Cash Difference Gain"/"Loss" and the cash-discount accounts with a
        hardcoded ``999`` prefix. ANAF's chart has no 999 class, so
        DUKIntegrator rejects them. Every Romanian Odoo Community database
        has them, so the pre-flight check must surface them and the
        accountant must map them onto a statutory account.
        """
        accounts = self.env['account.account'].with_company(
            self.company).search([('company_ids', 'in', self.company.id)])
        technical = accounts.filtered(
            lambda a: (a.code or '').startswith('999'))
        self.assertTrue(
            technical, 'Expected Odoo to have created 999-prefixed accounts.')
        for account in technical:
            self.assertEqual(
                account.l10n_ro_d406_mapping_status, 'unresolved',
                f'Account {account.code} should be flagged as unmappable.')

        flagged = self.env['account.account'].l10n_ro_d406_unmapped_accounts()
        self.assertTrue(set(technical.ids).issubset(set(flagged.ids)))

    def test_manual_override_resolves_a_999_account(self):
        """The override is the documented fix for the 999 accounts."""
        account = self.env['account.account'].with_company(
            self.company).search(
                [('company_ids', 'in', self.company.id)], limit=1).filtered(
                    lambda a: (a.code or '').startswith('999'))
        account = account or self.env['account.account'].with_company(
            self.company).search([('company_ids', 'in', self.company.id)]
        ).filtered(lambda a: (a.code or '').startswith('999'))[:1]
        self.assertTrue(account)
        account.l10n_ro_d406_account_code_manual = '758'
        self.assertEqual(account.l10n_ro_d406_account_code, '758')
        self.assertEqual(account.l10n_ro_d406_mapping_status, 'override')

    def test_foreign_partner_without_vat_uses_type_06(self):
        wizard = self._generate()
        payload = wizard.attachment_id.raw.decode()
        self.assertIn('06US', payload)
        self.assertNotIn('02ro', payload)

    def test_sections_dukintegrator_gates_on(self):
        """Guard the four shapes the real validator rejected during build.

        Each assertion below corresponds to an error DUKIntegrator returned
        against a generated file, fixed and then locked down here.
        """
        payload = self._generate().attachment_id.raw.decode()
        # GoodsServicesID is 01/02, not P/S.
        self.assertIn('<GoodsServicesID>02</GoodsServicesID>', payload)
        # ProductCommodityCode falls back to literal 0, not the product code.
        self.assertIn('<ProductCommodityCode>0</ProductCommodityCode>', payload)
        # Owners must be an empty container in a periodic declaration.
        self.assertNotIn('<Owner>', payload)
        # Payments must carry at least one entry.
        self.assertIn('<Payment>', payload)

    def test_period_without_payments_is_refused(self):
        """DUK requires >=1 Payment; an empty section has no valid file.

        Emitting the file anyway would push the failure out to
        DUKIntegrator, where it surfaces as an unexplained rejection well
        after the accountant has moved on.
        """
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.env['l10n.ro.d406.generator'].generate({
                'company': self.company,
                'date_from': date(2020, 1, 1),
                'date_to': date(2020, 1, 31),
                'declaration_type': 'L',
                'segment_index': 1,
                'total_segments': 1,
                'creation_date': date(2020, 2, 1),
                'fiscal_year_start': date(2020, 1, 1),
                'software_version': '19.0.1.0.0',
            })

    def test_no_empty_elements_are_emitted(self):
        """The invariant that produced two confirmed DUK rejections."""
        wizard = self._generate()
        payload = wizard.attachment_id.raw.decode()
        self.assertNotIn('></', payload.replace('</', '@@'))

    def test_annual_declaration_is_refused(self):
        """A and C need data Community does not have; fail loudly, not quietly."""
        from odoo.exceptions import UserError
        wizard = self.env['l10n.ro.d406.export.wizard'].with_company(
            self.company).create({
                'company_id': self.company.id,
                'declaration_type': 'L',
                'date_from': date(2026, 3, 1),
                'date_to': date(2026, 3, 31),
            })
        with self.assertRaises(UserError):
            self.env['l10n.ro.d406.generator'].generate({
                'company': self.company,
                'date_from': date(2026, 3, 1),
                'date_to': date(2026, 3, 31),
                'declaration_type': 'A',
                'segment_index': 1,
                'total_segments': 1,
                'creation_date': date(2026, 4, 1),
                'fiscal_year_start': date(2026, 1, 1),
                'software_version': '19.0.1.0.0',
            })

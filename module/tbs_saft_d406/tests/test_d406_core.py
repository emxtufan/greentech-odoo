# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Unit tests for the pure-Python core.

Every test here corresponds to a rejection DUKIntegrator issued against a
real production file. They need no database, so they run fast and fail loudly
if a refactor reintroduces one of the traps.
"""
from odoo.tests.common import BaseCase

from ..d406 import accountmap, registration, sanitize
from ..d406.xmlbuilder import AuditFile, EmptyRequiredValue

#: A small stand-in for the ANAF chart, mirroring the real hierarchy around
#: the two codes we have confirmed DUK verdicts for.
ANAF_CODES = {'1', '10', '101', '1012', '5', '58', '581', '8', '89', '891',
              '892', '6', '61', '612', '512', '5121'}


class TestSanitize(BaseCase):

    def test_iban_strips_spaces(self):
        """DUK rejects a space-separated IBAN as malformed for country RO."""
        self.assertEqual(
            sanitize.iban('RO49 AAAA 1B31 0075 9384 0000'),
            'RO49AAAA1B31007593840000')

    def test_account_id_keeps_leading_digits_only(self):
        """DUK: numar intreg eronat: '581.Stripe'."""
        self.assertEqual(sanitize.account_id('581.Stripe'), '581')
        self.assertEqual(sanitize.account_id('101200'), '101200')

    def test_account_id_without_digits_is_empty(self):
        self.assertEqual(sanitize.account_id('Stripe'), '')

    def test_cui_rejects_trade_register_number(self):
        """DUK: RegistrationNumber 00J40/10200/2009 formatul este invalid."""
        self.assertEqual(sanitize.cui('J40/10200/2009'), '')
        self.assertEqual(sanitize.cui('F12/345/2020'), '')

    def test_cui_strips_ro_prefix(self):
        self.assertEqual(sanitize.cui('RO12345674'), '12345674')

    def test_control_characters_are_stripped(self):
        """lxml refuses them outright; imports put them in partner names."""
        self.assertEqual(sanitize.text('Acme \x01Ltd'), 'Acme Ltd')
        self.assertEqual(sanitize.text('Acme\x00Ltd'), 'AcmeLtd')
        self.assertEqual(sanitize.text('Acme\x7fLtd'), 'AcmeLtd')
        # Tab and newline are whitespace, not illegal: collapsed, not dropped.
        self.assertEqual(sanitize.text('Acme\tLtd\nSRL'), 'Acme Ltd SRL')

    def test_region_only_for_romania(self):
        """DUK: Pentru tara 'IE' codul regiunii nu trebuie completat."""
        self.assertEqual(sanitize.region_code('RO', 'SB'), 'RO-SB')
        self.assertEqual(sanitize.region_code('IE', 'D'), '')
        self.assertEqual(sanitize.region_code('US', 'CA'), '')

    def test_monetary_has_no_negative_zero(self):
        self.assertEqual(sanitize.monetary(-0.001), '0.00')

    def test_monetary_rounds_half_up(self):
        self.assertEqual(sanitize.monetary('12.345'), '12.35')


class TestRegistration(BaseCase):

    def _identity(self, **kwargs):
        return registration.PartnerIdentity(**kwargs)

    def test_romanian_company_uses_type_00(self):
        self.assertEqual(
            registration.partner_registration_number(
                self._identity(vat='RO12345674', country_code='RO')),
            '0012345674')

    def test_eu_company_with_vat_uses_type_01(self):
        self.assertEqual(
            registration.partner_registration_number(
                self._identity(vat='DE123456789', country_code='DE')),
            '01DE123456789')

    def test_non_eu_company_without_vat_uses_type_06(self):
        """Enterprise falls through to '02ro' here, which DUK rejects."""
        result = registration.partner_registration_number(
            self._identity(country_code='US', partner_ref='FOREIGNCO',
                           partner_id=42))
        self.assertEqual(result, '06USFOREIGNCO')
        self.assertFalse(result.lower().startswith('02ro'))

    def test_eu_company_without_vat_uses_type_05(self):
        self.assertEqual(
            registration.partner_registration_number(
                self._identity(country_code='NL', partner_id=7)),
            '05NL7')

    def test_trade_register_number_never_reaches_output(self):
        self.assertEqual(
            registration.partner_registration_number(
                self._identity(company_registry='J40/10200/2009',
                               country_code='RO')),
            '')

    def test_company_header_keeps_ro_prefix(self):
        """The taxpayer's own header carries no type prefix, but keeps RO."""
        self.assertEqual(
            registration.company_header_registration_number(
                self._identity(vat='RO12345674', country_code='RO')),
            'RO12345674')

    def test_natural_person_uses_type_03(self):
        self.assertEqual(
            registration.partner_registration_number(
                self._identity(vat='1900101123456', country_code='RO',
                               is_company=False)),
            '031900101123456')


class TestAccountMap(BaseCase):

    def test_exact_match(self):
        result = accountmap.resolve('1012', ANAF_CODES)
        self.assertEqual(result.anaf_code, '1012')
        self.assertEqual(result.method, accountmap.Resolution.EXACT)

    def test_padded_code_resolves_by_prefix(self):
        """DUK accepted 101200 because 1012 exists and nothing longer does."""
        result = accountmap.resolve('101200', ANAF_CODES)
        self.assertEqual(result.anaf_code, '1012')
        self.assertEqual(result.method, accountmap.Resolution.PREFIX)

    def test_missing_root_is_unresolved(self):
        """DUK rejected 899000: no 899 root, only 891 and 892 under 89."""
        result = accountmap.resolve('899000', ANAF_CODES)
        self.assertFalse(result.is_resolved)
        self.assertEqual(result.method, accountmap.Resolution.UNRESOLVED)

    def test_non_numeric_suffix_is_stripped_then_resolved(self):
        result = accountmap.resolve('581.Stripe', ANAF_CODES)
        self.assertEqual(result.anaf_code, '581')

    def test_code_without_digits_is_flagged(self):
        result = accountmap.resolve('Stripe', ANAF_CODES)
        self.assertEqual(result.method, accountmap.Resolution.NOT_NUMERIC)

    def test_manual_override_wins(self):
        result = accountmap.resolve('899000', ANAF_CODES, override='892')
        self.assertEqual(result.anaf_code, '892')
        self.assertEqual(result.method, accountmap.Resolution.OVERRIDE)

    def test_prefix_index_matches_bruteforce(self):
        prefixes = accountmap.prefix_index(ANAF_CODES)
        for candidate in ('1', '10', '101', '1012', '58', '89'):
            self.assertIn(candidate, prefixes)
        self.assertNotIn('899', prefixes)


class TestXmlBuilder(BaseCase):

    def test_empty_optional_element_is_skipped(self):
        """An empty <ProductGroup> is a confirmed DUK rejection."""
        audit = AuditFile()
        node = audit.section('MasterFiles')
        node.add('ProductGroup', '')
        node.add('ProductGroup', None)
        node.add('ProductGroup', False)
        node.add('ProductGroup', '   ')
        self.assertNotIn(b'ProductGroup', audit.to_bytes())

    def test_non_empty_optional_element_is_written(self):
        audit = AuditFile()
        audit.section('MasterFiles').add('ProductGroup', 'Services')
        self.assertIn(b'<ProductGroup>Services</ProductGroup>',
                      audit.to_bytes())

    def test_empty_required_element_raises(self):
        audit = AuditFile()
        with self.assertRaises(EmptyRequiredValue):
            audit.section('Header').add_required('AuditFileCountry', '')

    def test_root_uses_the_namespace_dukintegrator_demands(self):
        """DUK rejects the XSD's own targetNamespace; DUK wins.

        Verified against the official validator: emitting the schema's
        ``d406t`` namespace produces "namespace (...) lipsa sau incorect la
        sectiunea AuditFile. Valoarea corecta este
        xmlns='mfp:anaf:dgti:d406:declaratie:v1'".
        """
        payload = AuditFile().to_bytes()
        self.assertIn(b'xmlns="mfp:anaf:dgti:d406:declaratie:v1"', payload)
        self.assertNotIn(b'd406t:declaratie', payload)

    def test_drop_if_empty_removes_container(self):
        audit = AuditFile()
        master = audit.section('MasterFiles')
        contact = master.child('Contact')
        self.assertTrue(contact.drop_if_empty())
        self.assertNotIn(b'Contact', audit.to_bytes())

import base64
from copy import deepcopy
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged, new_test_user
from odoo.addons.greentech_anaf_d112.services import document
from ..services import payroll as engine


def test_cnp(prefix="190010140001"):
    checksum = sum(int(a) * int(b) for a, b in zip(prefix, "279146358279")) % 11
    return prefix + str(1 if checksum == 10 else checksum)


def input_data(**updates):
    result = dict(year=2026, month=9, employee_id=1, cnp=test_cnp(), birthday="1990-01-01",
                  last_name="TEST", first_name="SOFTWARE", house="_B", profile="normal",
                  role="primary", dependents=0, children=0, minimum_status="eligible",
                  start="2026-07-01", end="", wage=8000, hours_week=40, hours_day=8,
                  version_changes=[], leave_count=0, worked_days=22, bonus=0, confirmed=True, standard_calendar=True)
    result.update(updates)
    return result


@tagged("post_install", "-at_install")
class TestNativePayroll(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].with_context(no_vat_validation=True).create({
            "name": "TEST NATIVE PAYROLL", "vat": "12345674", "company_registry": "TEST-NATIVE-UNIT",
            "currency_id": cls.env.ref("base.RON").id, "country_id": cls.env.ref("base.ro").id,
            "street": "STRADA TEST", "city": "TEST",
        })
        cls.user = new_test_user(cls.env(context=dict(cls.env.context, no_reset_password=True)),
            login="native_payroll_tester", groups="greentech_ro_payroll.group_payroll",
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.local = cls.env(context=dict(cls.env.context, allowed_company_ids=cls.company.ids))
        cal = cls.env.ref("resource.resource_calendar_std").copy({"name": "TEST 40h", "company_id": cls.company.id})
        cls.employee = cls.local["hr.employee"].create({
            "name": "TEST SOFTWARE NATIVE", "company_id": cls.company.id,
            "resource_calendar_id": cal.id, "identification_id": test_cnp(), "birthday": "1990-01-01",
            "ro_d112_last_name": "TEST", "ro_d112_first_name": "SOFTWARE", "ro_d112_house": "_B",
            "ro_d112_profile": "normal", "ro_d112_role": "primary", "ro_d112_minimum": "eligible",
        })
        cls.employee.version_id.write({"date_version": "2026-07-01", "contract_date_start": "2026-07-01",
                                       "wage": 8000, "resource_calendar_id": cal.id})
        cls.Model = cls.local["gt.ro.payroll.period"].with_user(cls.user)

    def period(self):
        record = self.Model.create({
            "company_id": self.company.id, "year": 2026, "month": "9", "caen": "6201",
            "house": "_B", "signer_last": "TEST", "signer_first": "SOFTWARE",
            "signer_position": "ADMINISTRATOR", "scope_confirmed": True,
        })
        record.action_load_employees()
        record.line_ids.write({"worked_days": 22, "confirmed": True})
        return record

    def test_standard_arithmetic(self):
        result = engine.calculate(input_data())
        self.assertEqual({k: result[k] for k in ("gross", "cas", "cass", "tax", "net")},
                         dict(gross=8000, cas=2000, cass=800, tax=520, net=4680))
        self.assertEqual(engine.totals([result])["cam"], 180)

    def test_minimum_and_personal_deduction(self):
        r = engine.calculate(input_data(wage=4325))
        self.assertEqual((r["exemption"], r["base"], r["cas"], r["cass"], r["personal"], r["tax"], r["net"]),
                         (200, 4125, 1031, 413, 865, 182, 2699))
        self.assertEqual(r["insured_type"], 51)
        self.assertEqual(engine.calculate(input_data(wage=4325, bonus=276))["exemption"], 0)
        with self.assertRaises(ValueError):
            engine.calculate(input_data(wage=4325, minimum_status=False))

    def test_deduction_table_boundaries_and_secondary(self):
        self.assertEqual(engine.calculate(input_data(wage=4375))["personal"], 843)
        self.assertEqual(engine.calculate(input_data(wage=4376))["personal"], 822)
        self.assertEqual(engine.calculate(input_data(wage=6326, dependents=4))["personal"], 0)
        self.assertEqual(engine.calculate(input_data(wage=4325, dependents=4))["personal"], 1946)
        self.assertEqual(engine.calculate(input_data(wage=8000, children=1))["deduction"], 100)
        r = engine.calculate(input_data(wage=4325, role="secondary"))
        self.assertEqual((r["exemption"], r["deduction"]), (0, 0))

    def test_cam_aggregate_rounding(self):
        r = engine.calculate(input_data(wage=8022))
        self.assertEqual(engine.totals([r, r])["cam"], 361)
        self.assertEqual(engine.integer(r["base"] * .0225) * 2, 360)

    def test_unsupported_cases_fail_closed(self):
        for updates in (dict(hours_week=20), dict(leave_count=1), dict(start="2026-09-02"),
                        dict(version_changes=[2]), dict(confirmed=False), dict(worked_days=21),
                        dict(profile="unsupported"), dict(cnp="1900101400010"), dict(wage=8000.5),
                        dict(birthday="2008-10-01", cnp=test_cnp("508100140001"))):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                engine.calculate(input_data(**updates))

    def test_native_flow_true_salary_and_original_schema_failure(self):
        record = self.period()
        record.action_compute()
        self.assertEqual(record.state, "calculated", record.calculation_log)
        self.assertEqual((record.gross, record.net, record.cam), (8000, 4680, 180))
        action = record.action_generate_d112()
        declaration = self.local["gt.anaf.d112"].browse(action["res_id"])
        self.assertEqual(declaration.payroll_period_id, record)
        self.assertEqual(declaration.state, "invalid")  # Published XSD defect, not a false pass.
        self.assertIn("A_sal1", declaration.schema_log)
        self.assertTrue(declaration.work_xml)
        self.assertFalse(declaration.xml_output)
        parsed = document.from_xml(base64.b64decode(declaration.work_xml))
        insured = next(n for n in parsed["children"] if n["tag"] == "asigurat")
        self.assertEqual(insured["children"][0]["attrs"]["A_sal1"], "8000")
        self.assertEqual([n["tag"] for n in insured["children"]], ["asiguratA", "asiguratE1", "asiguratE3"])
        self.assertEqual(record.action_generate_d112()["res_id"], declaration.id)
        with self.assertRaises(UserError):
            declaration.action_generate_pdf()

    def test_inputs_incomplete_reported_without_partial_calculation(self):
        record = self.period()
        record.line_ids.write({"confirmed": False})
        record.action_compute()
        self.assertEqual(record.state, "draft")
        self.assertIn("Confirmați", record.calculation_log)
        self.assertFalse(record.input_hash)
        with self.assertRaises(UserError):
            record.action_generate_d112()

    def test_minimum_declaration_type_51_and_aggregates(self):
        self.employee.version_id.write({"wage": 4325})
        record = self.period()
        record.action_compute()
        dec = self.local["gt.anaf.d112"].browse(record.action_generate_d112()["res_id"])
        employer, insured = dec.payload["children"]
        a = insured["children"][0]["attrs"]
        self.assertEqual((a["A_1"], a["A_13S"], a["A_13C"], a["A_13"]), ("51", "200", "4325", "4125"))
        c1 = next(n["attrs"] for n in employer["children"] if n["tag"] == "angajatorC1")
        self.assertEqual((c1["C1_11"], c1["C1_T"], c1["C1_5"]), ("4325", "0", "0"))
        self.assertEqual(record.cam, 93)
        with patch("odoo.addons.greentech_ro_payroll.models.payroll.duk.run",
                   return_value={"status": "unavailable", "report": "JAVA UNAVAILABLE TEST"}) as run:
            dec.action_validate_anaf()
            self.assertEqual(run.call_count, 1)

    def test_other_xml_errors_still_block_duk(self):
        record = self.period()
        record.action_compute()
        dec = self.local["gt.anaf.d112"].browse(record.action_generate_d112()["res_id"])
        invalid = deepcopy(dec.payload)
        invalid["attrs"]["nume_declar"] = ""
        dec._set({"payload": invalid})  # Simulate corruption through private server-side code.
        with patch("odoo.addons.greentech_ro_payroll.models.payroll.duk.run") as run:
            dec.action_validate_anaf()
            run.assert_not_called()
        self.assertEqual(dec.state, "invalid")

    def test_changed_contract_requires_recalculation(self):
        record = self.period()
        record.action_compute()
        self.employee.version_id.write({"wage": 9000})
        with self.assertRaises(UserError):
            record.action_generate_d112()

    def test_administrative_exclusion_never_hides_a_contract(self):
        admin = self.local["hr.employee"].create({
            "name": "TEST ADMIN NO PAYROLL", "company_id": self.company.id,
            "ro_d112_non_payroll": True, "ro_d112_exclusion_reason": "Fișă administrativă fără CIM",
        })
        record = self.period()
        self.assertNotIn(admin, record.line_ids.employee_id)
        self.employee.write({"ro_d112_non_payroll": True, "ro_d112_exclusion_reason": "TEST invalid exclusion"})
        with self.assertRaises(UserError):
            record.action_compute()

    def test_reset_invalidates_old_declaration_even_if_same_amounts(self):
        record = self.period()
        record.action_compute()
        old = self.local["gt.anaf.d112"].browse(record.action_generate_d112()["res_id"])
        record.action_reset()
        self.assertTrue(old.payroll_stale)
        self.assertFalse(old.work_xml)
        record.line_ids.write({"confirmed": True})
        record.action_compute()
        new = record.action_generate_d112()
        self.assertNotEqual(old.id, new["res_id"])
        with self.assertRaises(UserError):
            old.action_validate_anaf()

    def test_no_forged_amounts_or_source_or_context(self):
        record = self.period()
        with self.assertRaises(AccessError):
            record.write({"state": "calculated"})
        with self.assertRaises(AccessError):
            record.line_ids.write({"net": 100000})
        record.action_compute()
        dec = self.local["gt.anaf.d112"].browse(record.action_generate_d112()["res_id"])
        with self.assertRaises(UserError):
            dec.write({"payload": deepcopy(dec.payload)})
        with self.assertRaises(AccessError):
            dec.write({"payroll_hash": "forged"})
        forged = self.local["gt.anaf.d112"].with_context(default_state="valid", default_payroll_period_id=record.id).create({
            "company_id": self.company.id, "year": 2026, "month": "9"})
        self.assertEqual(forged.state, "draft")
        self.assertFalse(forged.payroll_period_id)

    def test_duk_runs_independently_only_for_documented_xsd_defects(self):
        record = self.period()
        record.action_compute()
        dec = self.local["gt.anaf.d112"].browse(record.action_generate_d112()["res_id"])
        with patch("odoo.addons.greentech_ro_payroll.models.payroll.duk.run",
                   return_value={"status": "unavailable", "report": "JAVA UNAVAILABLE TEST"}) as run:
            dec.action_validate_anaf()
            self.assertEqual(run.call_count, 1)
        self.assertEqual(dec.state, "invalid")
        self.assertFalse(dec.validated_hash)
        self.assertIn("JAVA UNAVAILABLE", dec.duk_log)
        # No test simulates fiscal acceptance as proof of real validation.

    def test_company_and_non_payroll_user_access(self):
        record = self.period()
        user = new_test_user(self.env(context=dict(self.env.context, no_reset_password=True)),
                            login="native_non_payroll", groups="base.group_user",
                            company_id=self.company.id, company_ids=[Command.set(self.company.ids)])
        with self.assertRaises(AccessError):
            record.with_user(user).read(["gross"])
        other = self.env["res.company"].create({"name": "OTHER PAYROLL TEST"})
        with self.assertRaises(AccessError):
            record.with_user(self.user).with_context(allowed_company_ids=other.ids).read(["gross"])

import base64
import re
from copy import deepcopy

from odoo import api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.greentech_anaf_d112.services import document
from odoo.addons.greentech_anaf_d112.services import duk
from lxml import etree
from odoo.addons.greentech_anaf_d112.models.declaration import MONTHS, RESET

from ..services import payroll as engine

GROUP = "greentech_ro_payroll.group_payroll"
PROFILE = [("normal", "CIM normal: rezident, nepensionar, fără scutiri / beneficii / alte venituri"),
           ("unsupported", "Altă situație — necesită implementare separată")]
HOUSES = [(code, code) for code in (
    "AB AR AG BC BH BN BT BV BR BZ CS CL CJ CT CV DB DJ GL GR GJ HR HD IL IS IF MM MH MS NT "
    "OT PH SM SJ SB SV TR TM TL VS VL VN _B _A _T").split()]


class Employee(models.Model):
    _inherit = "hr.employee"

    ro_d112_last_name = fields.Char("Nume de familie (D112)", groups=GROUP)
    ro_d112_first_name = fields.Char("Prenume (D112)", groups=GROUP)
    ro_d112_house = fields.Selection(HOUSES, "Casa de sănătate (D112)", groups=GROUP)
    ro_d112_profile = fields.Selection(PROFILE, "Încadrare salarială", groups=GROUP)
    ro_d112_role = fields.Selection([("primary", "Funcție de bază"), ("secondary", "În afara funcției de bază")],
                                    "Funcție fiscală", groups=GROUP)
    ro_d112_dependents = fields.Integer("Persoane în întreținere, documentate", groups=GROUP)
    ro_d112_children = fields.Integer("Copii eligibili pentru deducerea de 100 lei", groups=GROUP,
                                      help="Copii sub 18 ani înscriși la școală; documente și declarație de la părintele beneficiar.")
    ro_d112_minimum = fields.Selection([
        ("eligible", "Salariul nu a fost redus; condiția OUG 89/2025 verificată"),
        ("reduced", "Salariul a fost redus; nu se acordă facilitatea"),
    ], "Istoric pentru facilitatea de 200 lei", groups=GROUP)
    ro_d112_non_payroll = fields.Boolean("Fișă administrativă fără salariu", groups=GROUP,
        help="Exclude numai fișele administrative fără salariu și fără contract aplicabil în luna statului.")
    ro_d112_exclusion_reason = fields.Char("Motivul excluderii din salarizare", groups=GROUP)

    @api.constrains("ro_d112_non_payroll", "ro_d112_exclusion_reason")
    def _check_payroll_exclusion(self):
        for employee in self:
            if employee.ro_d112_non_payroll and not (employee.ro_d112_exclusion_reason or "").strip():
                raise ValidationError("Explicați de ce această fișă administrativă nu intră în salarizare.")


class Period(models.Model):
    _name = "gt.ro.payroll.period"
    _description = "Stat salarial România"
    _order = "year desc, month desc, id desc"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Firmă", required=True, default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    year = fields.Integer("An", required=True, default=2026)
    month = fields.Selection(MONTHS, "Lună", required=True, default=lambda s: str(fields.Date.context_today(s).month))
    state = fields.Selection([("draft", "Date de completat"), ("calculated", "Calculat"), ("generated", "D112 generată")],
                             "Stare", readonly=True, default="draft", copy=False)
    caen = fields.Char("CAEN principal", required=True, size=4)
    house = fields.Selection(HOUSES, "Casa de sănătate angajator", required=True)
    signer_last = fields.Char("Nume semnatar", required=True)
    signer_first = fields.Char("Prenume semnatar", required=True)
    signer_position = fields.Char("Funcție semnatar", required=True)
    scope_confirmed = fields.Boolean("Firma declară lunar, la sediul principal, numai veniturile acestor salariați",
        help="Nu bifați dacă există sedii secundare cu impozit separat, raportare trimestrială, alte categorii de venit sau regimuri speciale.")
    line_ids = fields.One2many("gt.ro.payroll.line", "period_id", "Salariați", copy=False)
    declaration_ids = fields.One2many("gt.anaf.d112", "payroll_period_id", "Declarații generate")
    snapshot = fields.Json("Datele calculului", readonly=True, copy=False)
    input_hash = fields.Char("Amprenta datelor", readonly=True, copy=False)
    calculation_log = fields.Text("Verificări și calcul", readonly=True, copy=False)
    calculated_at = fields.Datetime("Calculat la", readonly=True, copy=False)
    gross = fields.Monetary("Brut total", readonly=True, copy=False)
    cas = fields.Monetary("CAS", readonly=True, copy=False)
    cass = fields.Monetary("CASS", readonly=True, copy=False)
    tax = fields.Monetary("Impozit", readonly=True, copy=False)
    net = fields.Monetary("Net total", readonly=True, copy=False)
    cam = fields.Monetary("CAM", readonly=True, copy=False)
    due = fields.Monetary("Total obligații", readonly=True, copy=False)
    cost = fields.Monetary("Cost angajator", readonly=True, copy=False)
    _unique_period = models.Constraint("UNIQUE(company_id, year, month)", "Există deja un stat pentru firmă și lună.")
    _protected = {"state", "snapshot", "input_hash", "calculation_log", "calculated_at",
                  "gross", "cas", "cass", "tax", "net", "cam", "due", "cost", "declaration_ids"}

    @api.depends("company_id", "company_id.name", "year", "month")
    def _compute_name(self):
        for record in self:
            record.name = f"Salarii · {record.company_id.name} · {record.month}/{record.year}"

    @api.onchange("company_id")
    def _onchange_company(self):
        if "l10n_ro_caen_code" in self.company_id._fields:
            self.caen = self.company_id.l10n_ro_caen_code or False

    @api.constrains("year", "month", "caen")
    def _check_period(self):
        for record in self:
            try:
                engine.month_dates(record.year, record.month)
            except ValueError as exc:
                raise ValidationError(str(exc)) from None
            if not re.fullmatch(r"\d{4}", record.caen or ""):
                raise ValidationError("Codul CAEN trebuie să conțină patru cifre.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self._protected & vals.keys():
                raise AccessError("Rezultatele salariale sunt calculate de aplicație.")
            vals.update({key: False for key in self._protected - {"state", "declaration_ids"}})
            vals["state"] = "draft"
            vals["declaration_ids"] = []
        return super().create(vals_list)

    def _lock(self):
        self.ensure_one()
        self.check_access("write")
        self.env.cr.execute("SELECT id FROM gt_ro_payroll_period WHERE id=%s FOR UPDATE", (self.id,))
        self.invalidate_recordset()

    def _set(self, values):
        return super().write(values)

    def write(self, values):
        if self._protected & values.keys():
            raise AccessError("Rezultatele salariale sunt calculate de aplicație.")
        for record in self:
            record._lock()
            if record.state != "draft":
                raise UserError("Folosiți «Redeschide pentru corecții» înainte de modificarea unui stat calculat.")
            if {"company_id", "year", "month"} & values.keys() and record.line_ids:
                if any(values.get(k, record[k]) != (record[k].id if k == "company_id" else record[k])
                       for k in {"company_id", "year", "month"} & values.keys()):
                    raise UserError("Un stat cu salariați nu poate fi mutat la altă firmă/perioadă.")
        return super().write(values)

    def unlink(self):
        if any(r.state != "draft" or r.declaration_ids for r in self):
            raise UserError("Statele calculate sau cu declarații generate se păstrează.")
        return super().unlink()

    def _employees(self):
        start, end = engine.month_dates(self.year, self.month)
        employees = self.env["hr.employee"].with_context(active_test=False).search([("company_id", "=", self.company_id.id)])
        versions = self.env["hr.version"].with_context(active_test=False).search([
            ("employee_id", "in", employees.ids), ("contract_date_start", "<=", end),
            "|", ("contract_date_end", "=", False), ("contract_date_end", ">=", start)])
        candidates = employees.filtered(lambda e: e.active or e.id in versions.employee_id.ids)
        for employee in candidates.filtered("ro_d112_non_payroll"):
            if employee.id in versions.employee_id.ids or employee.version_id.wage:
                raise UserError(f"{employee.name}: fișa marcată nesalarizată are contract sau salariu. Corectați încadrarea.")
            if not (employee.ro_d112_exclusion_reason or "").strip():
                raise UserError(f"{employee.name}: lipsește motivul excluderii din salarizare.")
        return candidates.filtered(lambda e: not e.ro_d112_non_payroll)

    def action_load_employees(self):
        self._lock()
        if self.state != "draft":
            raise UserError("Redeschideți statul înainte de preluarea angajaților.")
        employees = self._employees()
        if not employees:
            raise UserError("Nu există angajați în această firmă. Completați fișele și contractele în aplicația Angajați.")
        new = employees - self.line_ids.employee_id
        self.write({"line_ids": [Command.create({"employee_id": emp.id}) for emp in new]})
        self._set({"calculation_log": "Angajații au fost preluați. Completați profilurile ANAF și pontajul real; apoi confirmați fiecare rând."})

    def _inputs(self):
        company = self.company_id
        return dict(profile=engine.PROFILE, company_id=company.id, vat=company.vat, name=company.name,
                    address=company.partner_id.contact_address, currency=company.currency_id.name,
                    year=self.year, month=self.month, caen=self.caen, house=self.house,
                    signer_last=self.signer_last, signer_first=self.signer_first, signer_position=self.signer_position,
                    scope=self.scope_confirmed, employees=sorted(self._employees().ids),
                    lines=[line._input() for line in self.line_ids.sorted("employee_id")])

    def action_compute(self):
        self._lock()
        if self.state != "draft":
            raise UserError("Redeschideți statul înainte de recalculare.")
        data = self._inputs()
        issues = []
        if data["currency"] != "RON":
            issues.append("Firma trebuie să utilizeze moneda RON.")
        if not self.scope_confirmed:
            issues.append("Confirmați încadrarea firmei în profilul lunar pentru sediul principal.")
        if not self.company_id.vat:
            issues.append("Completați CUI-ul firmei.")
        if not data["lines"] or sorted(self.line_ids.employee_id.ids) != data["employees"]:
            issues.append("Lista salariaților nu este completă. Folosiți «Preia angajați și contracte».")
        results = []
        seen = set()
        for line, values in zip(self.line_ids.sorted("employee_id"), data["lines"]):
            try:
                result = engine.calculate(values)
                if values["cnp"] in seen:
                    raise ValueError("CNP duplicat în stat.")
                seen.add(values["cnp"])
                results.append(result)
            except ValueError as exc:
                issues.append(f"{line.employee_id.name}: {exc}")
        if issues:
            self._set({"calculation_log": "\n".join(issues)})
            return
        for line, result in zip(self.line_ids.sorted("employee_id"), results):
            line._set({"result": result, **{k: result[k] for k in Line._amounts}})
        total = engine.totals(results)
        self._set({**{k: total[k] for k in ("gross", "cas", "cass", "tax", "net", "cam", "due", "cost")},
                   "snapshot": dict(inputs=data, results=results, totals=total),
                   "input_hash": engine.fingerprint(data), "state": "calculated", "calculated_at": fields.Datetime.now(),
                   "calculation_log": (
                       f"{len(results)} salariați calculați. CAS 25%; CASS 10%; impozit 10%; "
                       "CAM 2,25% din baza totală. Deduceri personale art.77; facilitate 200 lei OUG 89/2025, dacă este eligibilă. "
                       "Statul nu a fost postat în contabilitate. Declarația necesită validarea oficială DUKIntegrator.")})

    def _check_current(self, digest=None):
        self.ensure_one()
        self.check_access("read")
        if self.state not in ("calculated", "generated") or not self.input_hash:
            raise UserError("Statul sursă nu este calculat.")
        if (digest and digest != self.input_hash) or self.input_hash != engine.fingerprint(self._inputs()):
            raise UserError("Datele angajaților, contractelor sau firmei s-au modificat. Redeschideți statul, recalculați și generați o D112 nouă.")

    def action_generate_d112(self):
        self._lock()
        self._check_current()
        data = self.snapshot["inputs"]
        company = dict(attrs={
            "cif": re.sub(r"^RO", "", data["vat"].strip(), flags=re.I), "den": data["name"],
            "caen": data["caen"], "casaAng": data["house"], "adrSoc": data["address"] or "",
            "adrFisc": data["address"] or "",
        }, last_name=data["signer_last"], first_name=data["signer_first"], position=data["signer_position"])
        people = [dict(input=d, result=r) for d, r in zip(data["lines"], self.snapshot["results"])]
        payload = engine.declaration(company, self.year, self.month, people)
        existing = self.declaration_ids.filtered(lambda d: d.payroll_hash == self.input_hash and not d.payroll_stale)
        if existing:
            return existing[0]._form_action()
        record = self.env["gt.anaf.d112"].create({
            "company_id": self.company_id.id, "year": self.year, "month": self.month, "payload": payload,
            "revision": len(self.declaration_ids) + 1,
        })
        record._set({"payroll_period_id": self.id, "payroll_hash": self.input_hash})
        record._audit(f"Generată din statul Odoo {self.id}; profil {engine.PROFILE}. Nu este validată fiscal.")
        self._set({"state": "generated"})
        record.action_validate_schema()
        return record._form_action()

    def action_reset(self):
        self._lock()
        if any(d.receipt or d.filing_index for d in self.declaration_ids):
            raise UserError("Există o declarație cu index/recipisă. Rectificarea unui stat depus necesită un flux separat.")
        for record in self.declaration_ids:
            record._set(dict(RESET, payroll_stale=True))
            record._audit("Statul salarial sursă a fost redeschis. Este necesară o declarație nouă după recalculare.")
        self.line_ids._set({"result": False, **{key: 0 for key in Line._amounts}, "confirmed": False})
        self._set({"state": "draft", "input_hash": False, "snapshot": False, "calculated_at": False,
                   "calculation_log": "Stat redeschis; confirmați din nou datele și pontajele.",
                   **{k: 0 for k in ("gross", "cas", "cass", "tax", "net", "cam", "due", "cost")}})


class Line(models.Model):
    _name = "gt.ro.payroll.line"
    _description = "Salariat în statul lunar"
    _check_company_auto = True

    period_id = fields.Many2one("gt.ro.payroll.period", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="period_id.company_id", store=True)
    currency_id = fields.Many2one(related="period_id.currency_id")
    employee_id = fields.Many2one("hr.employee", "Angajat", required=True, check_company=True, ondelete="restrict")
    worked_days = fields.Integer("Zile efectiv lucrate")
    bonus = fields.Monetary("Prime brute (lei întregi)")
    confirmed = fields.Boolean("Pontaj și profil confirmate",
        help="Confirmați luna integral lucrată și profilul normal: fără concedii, suspendări, beneficii, ore suplimentare, diurne ori alte venituri/deduceri.")
    result = fields.Json(readonly=True, copy=False)
    gross = fields.Monetary("Brut", readonly=True, copy=False)
    exemption = fields.Monetary("Sumă netaxabilă", readonly=True, copy=False)
    cas = fields.Monetary("CAS", readonly=True, copy=False)
    cass = fields.Monetary("CASS", readonly=True, copy=False)
    deduction = fields.Monetary("Deduceri personale", readonly=True, copy=False)
    tax = fields.Monetary("Impozit", readonly=True, copy=False)
    net = fields.Monetary("Net", readonly=True, copy=False)
    _amounts = ("gross", "exemption", "cas", "cass", "deduction", "tax", "net")
    _unique_employee = models.Constraint("UNIQUE(period_id, employee_id)", "Angajatul apare deja în acest stat.")

    def _set(self, values):
        return super().write(values)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if (set(self._amounts) | {"result"}) & values.keys():
                raise AccessError("Sumele sunt calculate de aplicație.")
            period = self.env["gt.ro.payroll.period"].browse(values["period_id"])
            period._lock()
            if period.state != "draft":
                raise UserError("Statul trebuie redeschis înainte de adăugarea salariaților.")
            values.update(result=False, **{key: 0 for key in self._amounts})
        return super().create(vals_list)

    def write(self, values):
        if (set(self._amounts) | {"result", "period_id"}) & values.keys():
            raise AccessError("Sumele și apartenența la stat nu se modifică manual.")
        for period in self.period_id:
            period._lock()
            if period.state != "draft":
                raise UserError("Statul trebuie redeschis înainte de modificarea datelor.")
        if {"employee_id", "worked_days", "bonus"} & values.keys() and "confirmed" not in values:
            values = dict(values, confirmed=False)
        return super().write(values)

    def unlink(self):
        for period in self.period_id:
            period._lock()
            if period.state != "draft":
                raise UserError("Nu puteți elimina salariați dintr-un stat calculat.")
        return super().unlink()

    def _input(self):
        self.ensure_one()
        employee, period = self.employee_id, self.period_id
        start, end = engine.month_dates(period.year, period.month)
        versions = self.env["hr.version"].with_context(active_test=False).search([
            ("employee_id", "=", employee.id), ("date_version", "<=", start)], order="date_version desc, id desc", limit=1)
        version = versions[:1]
        changes = self.env["hr.version"].with_context(active_test=False).search([
            ("employee_id", "=", employee.id), ("date_version", ">", start), ("date_version", "<=", end)])
        leaves = self.env["hr.leave"].search([
            ("employee_id", "=", employee.id), ("state", "not in", ["cancel", "refuse"]),
            ("request_date_from", "<=", end), ("request_date_to", ">=", start)])
        cal = version.resource_calendar_id
        weekdays = {str(i): 0 for i in range(7)}
        for attendance in cal.attendance_ids.filtered(lambda a: not a.display_type and a.day_period != "lunch"):
            weekdays[attendance.dayofweek] += attendance.hour_to - attendance.hour_from
        standard_calendar = (not cal.two_weeks_calendar and
                             all(weekdays[str(i)] == (8 if i < 5 else 0) for i in range(7)))
        return dict(employee_id=employee.id, employee_active=employee.active, company_id=employee.company_id.id,
                    year=period.year, month=period.month, cnp=employee.identification_id or "",
                    birthday=str(employee.birthday) if employee.birthday else "",
                    last_name=employee.ro_d112_last_name, first_name=employee.ro_d112_first_name,
                    house=employee.ro_d112_house, profile=employee.ro_d112_profile, role=employee.ro_d112_role,
                    dependents=employee.ro_d112_dependents, children=employee.ro_d112_children,
                    minimum_status=employee.ro_d112_minimum,
                    version_id=version.id, start=str(version.contract_date_start) if version.contract_date_start else "",
                    end=str(version.contract_date_end) if version.contract_date_end else "",
                    wage=version.wage or 0, hours_week=cal.hours_per_week or 0, hours_day=cal.hours_per_day or 0,
                    standard_calendar=standard_calendar,
                    version_changes=changes.ids, leave_count=len(leaves), leave_ids=leaves.ids,
                    worked_days=self.worked_days, bonus=self.bonus, confirmed=self.confirmed)

    def action_employee(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "hr.employee", "res_id": self.employee_id.id, "view_mode": "form"}


class Declaration(models.Model):
    _inherit = "gt.anaf.d112"

    payroll_period_id = fields.Many2one("gt.ro.payroll.period", "Stat salarial sursă", readonly=True, copy=False, ondelete="restrict", check_company=True)
    payroll_hash = fields.Char("Amprenta statului", readonly=True, copy=False)
    payroll_stale = fields.Boolean("Stat redeschis", readonly=True, copy=False)
    work_xml = fields.Binary("XML de lucru — NEVALIDAT", compute="_compute_work_xml")
    work_filename = fields.Char(compute="_compute_work_xml")

    @api.depends("payload", "year", "month", "payroll_stale")
    def _compute_work_xml(self):
        for record in self:
            record.work_filename = f"D112_LUCRU_NEVALIDAT_{record.year}_{record.month}.xml"
            current = True
            try:
                record._source_check()
            except UserError:
                current = False
            record.work_xml = base64.b64encode(document.to_xml(record.payload)) if record.payload and current else False

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if {"payroll_period_id", "payroll_hash", "payroll_stale", "work_xml", "work_filename"} & values.keys():
                raise AccessError("Legătura cu statul se creează prin generarea D112.")
            values.update(payroll_period_id=False, payroll_hash=False, payroll_stale=False)
        return super().create(vals_list)

    def write(self, values):
        if {"payroll_period_id", "payroll_hash", "payroll_stale", "work_xml", "work_filename"} & values.keys():
            raise AccessError("Legătura cu statul nu se modifică manual.")
        if {"payload", "year", "month", "company_id"} & values.keys() and any(self.mapped("payroll_period_id")):
            raise UserError("Declarația provine din statul salarial. Corectați și recalculați statul pentru a genera alt dosar.")
        return super().write(values)

    def _source_check(self):
        self.ensure_one()
        if self.payroll_period_id:
            if self.payroll_stale:
                raise UserError("Această declarație provine dintr-un stat redeschis. Generați o declarație nouă.")
            self.payroll_period_id._check_current(self.payroll_hash)

    def _validate_schema(self):
        self._source_check()
        raw, issues = super()._validate_schema()
        if issues and self.payroll_period_id:
            self._set({"schema_log": self.schema_log + "\n\n"
                "Schema publicată 140826 limitează A_sal1/A_sal2 la 30 și tipul A_1 la 30. "
                "Anexa ANAF descrie salariile ca N(15) și include tipul 51. "
                "XSD-ul original și sumele reale au fost păstrate. XML-ul de lucru nu reprezintă o declarație validată."})
        return raw, issues

    def action_generate_pdf(self):
        self._source_check()
        return super().action_generate_pdf()

    def action_validate_anaf(self):
        if not self.payroll_period_id:
            return super().action_validate_anaf()
        self._lock()
        raw, issues = self._validate_schema()
        if issues:
            # Diagnostic only. Keep the user's ORIGINAL schema and its report.
            # Exact pinned schema; change only the three documented discrepancies
            # in a separate in-memory copy before permitting independent DUK.
            schema_path = document.BASE / "schemas/d112_0726.xsd"
            if document.fingerprint(schema_path.read_bytes()) != "9603d3aa1b0bd7b56f91584e41ecdc3a09dda3abf724631f42f27c24b9b45788":
                return
            tree = deepcopy(document.schema_tree())
            for element in tree.xpath("//xs:complexType[@name='AsiguratAType']//xs:attribute",
                                      namespaces={"xs": "http://www.w3.org/2001/XMLSchema"}):
                if element.get("name") in ("A_sal1", "A_sal2"):
                    element.set("type", "IntPoz15SType")
                elif element.get("name") == "A_1":
                    element.set("type", "IntPoz3SType")
            root = etree.fromstring(raw, document.parser())
            if not etree.XMLSchema(tree).validate(root):
                return
            if any(n.get("A_1") not in ("1", "51") for n in root.findall(".//{" + document.NS + "}asiguratA")):
                return
            self._set({"schema_log": self.schema_log + "\n"
                       "Diagnostic: numai cele trei neconcordanțe documentate. Se solicită verificarea independentă DUK; XSD strict rămâne nereușit."})
        dist, java = self._runtime_paths()
        result = duk.run(raw, dist, java)
        state = {"valid": "valid", "warnings": "warnings", "invalid": "invalid",
                 "unavailable": "invalid" if issues else "xsd"}[result["status"]]
        values = {"state": state, "duk_log": result["report"],
                  "validated_hash": document.fingerprint(raw) if state == "valid" else False,
                  "validated_at": fields.Datetime.now() if state == "valid" else False,
                  "validator_manifest": result.get("runtime") or False}
        if state == "valid":
            values.update(xml_output=base64.b64encode(raw),
                          xml_filename=f"D112_{self.year}_{self.month}_{self.company_id.id}.xml")
        self._set(values)
        self._audit("DUKIntegrator: " + result["status"], document.fingerprint(raw))

    def action_revision(self):
        if self.payroll_period_id:
            raise UserError("Pentru o D112 generată din salarii, corectați statul și generați un dosar nou.")
        return super().action_revision()

    def _form_action(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form"}

import base64
from copy import deepcopy
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services import document, duk

MONTHS = [(str(n), f"{n:02d}") for n in range(1, 13)]
SYSTEM_FIELDS = {
    "state", "schema_log", "duk_log", "validated_hash", "validated_at", "validator_manifest",
    "xml_output", "xml_filename", "pdf_output", "pdf_filename", "source_hash", "audit_log",
    "source_xml", "source_filename", "schema_version",
}
RESET = {
    "state": "draft", "schema_log": False, "duk_log": False, "validated_hash": False,
    "validated_at": False, "validator_manifest": False, "xml_output": False,
    "xml_filename": False, "pdf_output": False, "pdf_filename": False,
}


class Declaration(models.Model):
    _name = "gt.anaf.d112"
    _description = "ANAF — Declarația 112"
    _order = "year desc, month desc, id desc"
    _check_company_auto = True

    name = fields.Char("Declarație", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Firmă", required=True, default=lambda s: s.env.company, index=True)
    year = fields.Integer("An", required=True, default=lambda s: fields.Date.context_today(s).year)
    month = fields.Selection(MONTHS, "Lună", required=True, default=lambda s: str(fields.Date.context_today(s).month))
    revision = fields.Integer("Revizie dosar", default=1, required=True)
    payload = fields.Json("Conținut declarație", default=dict, copy=True)
    state = fields.Selection([
        ("draft", "În lucru"), ("invalid", "Erori"), ("xsd", "Structură XML verificată"),
        ("warnings", "Atenționări ANAF"), ("valid", "Validat DUKIntegrator"),
        ("pdf", "PDF ANAF generat"),
    ], string="Stare", default="draft", readonly=True, copy=False)
    schema_version = fields.Char("Schema", default=document.PROFILE["version"], readonly=True)
    schema_log = fields.Text("Verificare structură", readonly=True, copy=False)
    duk_log = fields.Text("Rezultat validator ANAF", readonly=True, copy=False)
    validated_hash = fields.Char("Amprenta XML validat", readonly=True, copy=False)
    validated_at = fields.Datetime("Validat la", readonly=True, copy=False)
    validator_manifest = fields.Json("Versiunea fișierelor validatorului", readonly=True, copy=False)
    upload = fields.Binary("XML existent (opțional)", attachment=False, copy=False)
    upload_filename = fields.Char("Nume fișier import", copy=False)
    source_xml = fields.Binary("XML sursă original", attachment=True, readonly=True, copy=False)
    source_filename = fields.Char("Nume sursă", readonly=True, copy=False)
    source_hash = fields.Char("Amprenta sursei", readonly=True, copy=False)
    xml_output = fields.Binary("XML generat", attachment=True, readonly=True, copy=False)
    xml_filename = fields.Char(readonly=True, copy=False)
    pdf_output = fields.Binary("PDF ANAF nesemnat", attachment=True, readonly=True, copy=False)
    pdf_filename = fields.Char(readonly=True, copy=False)
    receipt = fields.Binary("Recipisă primită de la ANAF", attachment=True, copy=False)
    receipt_filename = fields.Char("Nume recipisă", copy=False)
    filing_index = fields.Char("Index de încărcare ANAF", copy=False)
    filing_note = fields.Text("Observații privind depunerea", copy=False)
    audit_log = fields.Text("Istoric verificări", readonly=True, copy=False)
    runtime_status = fields.Text("Disponibilitate validator", compute="_compute_runtime")
    insured_count = fields.Integer("Asigurați", compute="_compute_summary")
    total_payment = fields.Char("Total de plată declarat", compute="_compute_summary")
    schema_url = fields.Char(default=document.PROFILE["index_url"], readonly=True)

    @api.depends("company_id.name", "year", "month", "revision")
    def _compute_name(self):
        for record in self:
            record.name = f"D112 · {record.company_id.name or ''} · {record.month or '?'}/{record.year} · r{record.revision}"

    @api.depends("payload")
    def _compute_summary(self):
        for record in self:
            nodes = (record.payload or {}).get("children", [])
            record.insured_count = sum(n.get("tag") == "asigurat" for n in nodes)
            employer = next((n for n in nodes if n.get("tag") == "angajator"), {})
            record.total_payment = employer.get("attrs", {}).get("totalPlata_A", "")

    def _runtime_paths(self):
        return duk.resolve_duk_dir(self.env, "gt_anaf.duk_dir", "duk"), duk.resolve_java(self.env)

    def _compute_runtime(self):
        dist, java = self._runtime_paths()
        _, issues = duk.readiness(dist, java)
        for record in self:
            record.runtime_status = "\n".join(issues) if issues else "Fișierele validatorului și Java sunt disponibile. Validarea se execută pentru fiecare XML."

    @api.model
    def editor_schema(self):
        if not self.env.user.has_group("greentech_anaf_d112.group_anaf"):
            raise AccessError("Nu aveți acces la declarațiile ANAF.")
        return document.editor_schema()

    def _lock(self):
        self.ensure_one()
        self.check_access("write")
        self.env.cr.execute("SELECT id FROM gt_anaf_d112 WHERE id=%s FOR UPDATE", (self.id,))
        self.invalidate_recordset()

    def _set(self, values):
        return super(Declaration, self).write(values)

    def _audit(self, action, digest=""):
        entry = f"{fields.Datetime.now()} | {self.env.user.id} | {action} | {digest}"
        self._set({"audit_log": ((self.audit_log or "") + "\n" + entry).strip()})

    @api.constrains("year", "month", "revision")
    def _check_period(self):
        for record in self:
            try:
                document.period_check(record.year, record.month)
            except ValueError as exc:
                raise ValidationError(str(exc)) from None
            if record.revision < 1:
                raise ValidationError("Revizia trebuie să fie pozitivă.")

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if SYSTEM_FIELDS & values.keys():
                raise AccessError("Rezultatul validării este generat exclusiv de aplicație.")
            if values.get("payload"):
                try:
                    values["payload"] = document.normalize(values["payload"])
                except ValueError as exc:
                    raise ValidationError(str(exc)) from None
            # RPC context default_* must not forge validation results either.
            values.update(RESET)
            values.update(source_xml=False, source_filename=False, source_hash=False,
                          audit_log=False, validator_manifest=False, schema_version=document.PROFILE["version"])
        return super().create(vals_list)

    def write(self, values):
        values = dict(values)
        if SYSTEM_FIELDS & values.keys():
            raise AccessError("Rezultatele și fișierele validate nu se modifică manual.")
        if {"payload", "year", "month", "company_id"} & values.keys():
            for record in self:
                record._lock()
                if record.receipt or record.filing_index:
                    raise UserError("Dosarul are o recipisă sau un index. Creați o revizie pentru modificări.")
            if "payload" in values:
                try:
                    values["payload"] = document.normalize(values["payload"])
                except ValueError as exc:
                    raise ValidationError(str(exc)) from None
            # This private super-write keeps clients from forging a green status.
            result = super().write(dict(values, **RESET))
            for record in self:
                record._audit("Conținut modificat; validarea anterioară a fost anulată")
            return result
        return super().write(values)

    def unlink(self):
        if any(r.state != "draft" or r.receipt or r.filing_index for r in self):
            raise UserError("Un dosar validat sau depus se păstrează în arhivă.")
        return super().unlink()

    def action_prepare(self):
        self._lock()
        if self.payload:
            raise UserError("Dosarul are deja date. Creați alt dosar pentru o declarație nouă.")
        company = self.company_id
        cif = re.sub(r"^RO", "", (company.vat or "").strip(), flags=re.I)
        data = document.new_document(self.year, self.month, {
            "cif": cif, "den": company.name, "rgCom": company.company_registry,
            "adrSoc": company.partner_id.contact_address,
            "telSoc": company.phone, "mailSoc": company.email,
            "caen": company.l10n_ro_caen_code if "l10n_ro_caen_code" in company._fields else "",
        })
        self.write({"payload": data})
        self._audit("Date identificare angajator preluate; valorile salariale se completează separat")

    def action_import(self):
        self._lock()
        if not self.upload:
            raise UserError("Selectați fișierul XML.")
        if self.payload:
            raise UserError("Importul se face într-un dosar gol, pentru a păstra datele deja introduse.")
        try:
            if len(self.upload) > document.MAX_BYTES * 4 // 3 + 8:
                raise ValueError("Fișierul depășește 16 MB.")
            raw = base64.b64decode(self.upload, validate=True)
            payload = document.from_xml(raw)
            employer = next(n for n in payload["children"] if n["tag"] == "angajator")
            cif = re.sub(r"^RO", "", (self.company_id.vat or "").strip(), flags=re.I)
            if employer["attrs"].get("cif") != cif:
                raise ValueError("XML-ul aparține altei firme. Selectați firma corectă înainte de import.")
            if int(payload["attrs"]["an_r"]) != self.year or int(payload["attrs"]["luna_r"]) != int(self.month):
                raise ValueError("Luna/anul XML nu corespund dosarului.")
        except (ValueError, KeyError, StopIteration) as exc:
            raise UserError(str(exc) or "XML fără angajator.") from None
        self.write({"payload": payload})
        self._set({"source_xml": base64.b64encode(raw), "source_filename": self.upload_filename or "sursa.xml",
                   "source_hash": document.fingerprint(raw), "upload": False})
        self._audit("XML importat fără recalculare sau eliminarea secțiunilor", self.source_hash)

    def _validate_schema(self):
        if not self.payload:
            raise UserError("Generați declarația dintr-un stat salarial sau completați datele dosarului.")
        try:
            raw, issues = document.validate(self.payload, self.company_id.vat, self.year, self.month)
        except (ValueError, TypeError) as exc:
            raise UserError(str(exc)) from None
        self._set(dict(RESET, state="invalid" if issues else "xsd",
                       schema_log="\n".join(issues) if issues else
                       "Structura respectă schema oficială XSD. Calculele și regulile fiscale necesită validarea DUKIntegrator."))
        if not issues:
            cif = re.sub(r"\D", "", self.company_id.vat or "")
            self._set({"xml_output": base64.b64encode(raw),
                       "xml_filename": f"D112_{self.year}_{int(self.month):02d}_{cif}.xml"})
        self._audit("XSD: erori" if issues else "XSD: structură verificată", document.fingerprint(raw))
        return raw, issues

    def action_validate_schema(self):
        self._lock()
        self._validate_schema()

    def action_validate_anaf(self):
        self._lock()
        raw, issues = self._validate_schema()
        if issues:
            return
        dist, java = self._runtime_paths()
        result = duk.run(raw, dist, java)
        state = {"valid": "valid", "warnings": "warnings", "invalid": "invalid", "unavailable": "xsd"}[result["status"]]
        self._set({"state": state, "duk_log": result["report"],
                   "validated_hash": document.fingerprint(raw) if state == "valid" else False,
                   "validated_at": fields.Datetime.now() if state == "valid" else False,
                   "validator_manifest": result.get("runtime") or False})
        self._audit("DUKIntegrator: " + result["status"], document.fingerprint(raw))

    def action_generate_pdf(self):
        self._lock()
        if self.state not in ("valid", "pdf") or not self.validated_hash:
            raise UserError("Mai întâi validați declarația cu DUKIntegrator.")
        raw = document.to_xml(self.payload)
        if document.fingerprint(raw) != self.validated_hash:
            raise UserError("Declarația s-a modificat. Validați din nou.")
        dist, java = self._runtime_paths()
        result = duk.run(raw, dist, java, make_pdf=True)
        values = {"duk_log": result["report"], "pdf_output": False, "pdf_filename": False}
        if result["status"] == "valid" and result.get("pdf"):
            values.update(state="pdf", pdf_output=base64.b64encode(result["pdf"]),
                          pdf_filename=self.xml_filename.removesuffix(".xml") + ".pdf")
        else:
            values.update(state="invalid", validated_hash=False, validated_at=False)
        self._set(values)
        self._audit("PDF ANAF: " + result["status"], document.fingerprint(raw))

    def action_compare_source(self):
        self.ensure_one()
        self.check_access("read")
        if not self.source_xml or not self.payload:
            raise UserError("Comparația necesită un XML sursă importat.")
        equal = document.semantic_equal(base64.b64decode(self.source_xml), document.to_xml(self.payload))
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": "Comparație cu XML-ul sursă", "message": "Toate secțiunile și valorile coincid." if equal else
            "Există diferențe față de sursa importată.", "type": "success" if equal else "warning", "sticky": True,
        }}

    def action_revision(self):
        self.ensure_one()
        self.check_access("read")
        record = self.create({"company_id": self.company_id.id, "year": self.year, "month": self.month,
                              "revision": self.revision + 1, "payload": deepcopy(self.payload)})
        record._audit(f"Revizie creată din dosarul {self.id}. Tipul rectificării nu se schimbă automat.")
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": record.id, "view_mode": "form"}

import base64
import csv
from datetime import date
from io import StringIO
import json
import re
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.greentech_anaf_d112.services.duk import resolve_duk_dir, resolve_java
from ..services import calculation as calc, runtime


class TaxMapping(models.Model):
    _name = "gt.d300.mapping"
    _description = "Încadrare taxă pe rând D300"
    _check_company_auto = True
    _rec_name = "tax_id"
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company, string="Firmă")
    tax_id = fields.Many2one("account.tax", required=True, check_company=True, string="Taxă Odoo")
    kind = fields.Selection([("purchase", "Deductibilă"), ("sale", "Colectată")], required=True, string="Latură")
    row_code = fields.Selection(calc.INPUT_ROWS, required=True, string="Rând D300")
    prorata = fields.Boolean("Aplică pro-rata", help="Numai pentru achiziții mixte supuse pro-rata. Limitarea 50/100% se preia separat din contabilitate.")
    note = fields.Char("Justificare / temei")
    _unique_tax_side = models.Constraint("UNIQUE(company_id, tax_id, kind)", "Există deja o încadrare pentru această taxă și latură.")

    @api.constrains("row_code", "kind", "prorata")
    def _check_row(self):
        for rec in self:
            valid = dict(calc.BUY_ROWS if rec.kind == "purchase" else calc.SALE_ROWS)
            if rec.row_code not in valid or rec.prorata and (rec.kind != "purchase" or not 20 <= float(rec.row_code) <= 28):
                raise ValidationError("Rândul sau pro-rata nu corespunde laturii taxei.")

    @api.model
    def seed_standard(self, company):
        """Only known, unchanged Romanian chart-template taxes; never names guessed."""
        if company not in self.env.companies:
            raise AccessError("Firmă neautorizată.")
        taxes = self.env["account.tax"].with_context(active_test=False).search([("company_id", "=", company.id)])
        xmlids = taxes.get_external_id()
        existing = {(r.tax_id.id, r.kind) for r in self.search([("company_id", "=", company.id)])}
        # Template IDs are checked below against source tax semantics, not label alone.
        created = 0
        for tax in taxes:
            xid = xmlids.get(tax.id, "")
            if not re.fullmatch(r"account\.\d+_tva[cd]_?(?:21|11)(?:_s)?|account\.\d+_tvai[cd]_(?:21|11)", xid):
                continue
            if tax.amount_type != "percent" or tax.amount not in (21, 11):
                continue
            label = tax.name.upper()
            # Foreign/reverse-charge/deduction-special templates need explicit review.
            if not re.fullmatch(r"(21|11)%( G| S)?", label):
                continue
            kind = tax.type_tax_use
            if kind not in ("purchase", "sale") or (tax.id, kind) in existing:
                continue
            row = {("sale", 21): "9", ("sale", 11): "10",
                   ("purchase", 21): "24", ("purchase", 11): "25"}[kind, int(tax.amount)]
            self.create({"company_id": company.id, "tax_id": tax.id, "kind": kind, "row_code": row,
                         "note": "Taxă standard din planul RO; verificați utilizarea fiscală a documentelor."})
            created += 1
        return created


class Adjustment(models.Model):
    _name = "gt.d300.adjustment"
    _description = "Regularizare documentată D300"
    _check_company_auto = True
    declaration_id = fields.Many2one("gt.anaf.d300", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="declaration_id.company_id", store=True)
    row_code = fields.Selection(calc.INPUT_ROWS, required=True, string="Rând")
    base = fields.Float("Bază (+/−)", digits=(18, 2))
    tax = fields.Float("TVA (+/−)", digits=(18, 2))
    eligible = fields.Float("TVA efectiv dedusă", digits=(18, 2),
        help="Pentru rândurile 20–28. Nu este egală obligatoriu cu TVA brută; se introduce după limitări/pro-rata.")
    reason = fields.Char("Justificare obligatorie", required=True)
    evidence = fields.Char("Document / referință", required=True)

    @api.constrains("row_code", "base", "tax", "eligible", "reason", "evidence")
    def _check_values(self):
        for rec in self:
            if not (rec.reason or "").strip() or not (rec.evidence or "").strip():
                raise ValidationError("Justificarea și documentul sunt obligatorii.")
            row = calc.BY_ROW[rec.row_code]
            if rec.base and not row[2] or rec.tax and not row[3]:
                raise ValidationError("Rândul ales nu are această coloană.")
            if rec.eligible and not 20 <= float(rec.row_code) <= 28:
                raise ValidationError("TVA efectiv dedusă se completează numai pentru rândurile 20–28.")

    @api.model_create_multi
    def create(self, vals_list):
        result = super().create(vals_list)
        result.declaration_id._invalidate()
        return result

    def write(self, vals):
        parents = self.declaration_id
        result = super().write(vals)
        (parents | self.declaration_id)._invalidate()
        return result

    def unlink(self):
        parents = self.declaration_id
        result = super().unlink()
        parents._invalidate()
        return result


class ExtraInfo(models.Model):
    _name = "gt.d300.info"
    _description = "Informație suplimentară D300"
    _check_company_auto = True
    declaration_id = fields.Many2one("gt.anaf.d300", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="declaration_id.company_id", store=True)
    code = fields.Selection(list(calc.INFO.items()), required=True, string="Indicator")
    value = fields.Float("Ajustare (+/−)", digits=(18, 2))
    reason = fields.Char("Justificare / document", required=True)

    @api.model_create_multi
    def create(self, vals_list):
        result = super().create(vals_list)
        result.declaration_id._invalidate()
        return result

    def write(self, vals):
        parents = self.declaration_id
        result = super().write(vals)
        (parents | self.declaration_id)._invalidate()
        return result

    def unlink(self):
        parents = self.declaration_id
        result = super().unlink()
        parents._invalidate()
        return result


class Declaration(models.Model):
    _name = "gt.anaf.d300"
    _description = "D300 — Decont TVA"
    _order = "year desc, month desc, id desc"
    _check_company_auto = True

    name = fields.Char(compute="_name_compute", store=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company, string="Firmă")
    year = fields.Integer("An", required=True, default=2026)
    month = fields.Integer("Luna de final", required=True, default=lambda s: fields.Date.today().month)
    period_type = fields.Selection([("L", "Lunar"), ("T", "Trimestrial"), ("S", "Semestrial"), ("A", "Anual")],
                                   string="Perioadă fiscală", default="L", required=True)
    date_from = fields.Date("Început", compute="_dates")
    date_to = fields.Date("Sfârșit", compute="_dates")
    vat_registered = fields.Boolean("Confirm înregistrarea TVA art. 316 pentru această perioadă")
    balances_reviewed = fields.Boolean("Am verificat soldurile reportate, plățile și deciziile fiscale",
        help="Rândurile 38/41 nu se deduc automat din soldul curent 4423/4424. Verificați decontul precedent și plățile până la depunere.")
    special_reviewed = fields.Boolean("Am verificat situațiile speciale și informațiile suplimentare",
        help="Facturi după inspecție/reînregistrare, taxare inversă pe categorii, vânzări art. 278¹, excluderi legale.")
    prorata = fields.Float("Pro-rata (%)", default=100, digits=(5, 2))
    refund = fields.Boolean("Solicit rambursarea TVA")
    simplified = fields.Boolean("Decont simplificat — operațiuni interne")
    legal_basis = fields.Selection([("0", "Nu se aplică"), ("2", "După anularea rezervei verificării ulterioare")],
                                  default="0", required=True, string="Temei special")
    successor_cui = fields.Char("CUI succesor")
    consolidated = fields.Boolean("Decont consolidat grup fiscal",
        help="Consolidarea automată între persoane juridice nu este disponibilă. Exportul este blocat dacă această opțiune este bifată.")
    signer_last = fields.Char("Nume declarant")
    signer_first = fields.Char("Prenume declarant")
    signer_role = fields.Char("Funcție declarant")
    caen = fields.Char("CAEN activitate preponderentă")
    bank_name = fields.Char("Bancă")
    bank_account = fields.Char("Cont IBAN")
    cereals = fields.Boolean("Livrări cereale / plante tehnice")
    mobiles = fields.Boolean("Livrări telefoane mobile")
    chips = fields.Boolean("Livrări circuite integrate")
    consoles = fields.Boolean("Livrări console / tablete / laptopuri")
    adjustment_ids = fields.One2many("gt.d300.adjustment", "declaration_id", string="Regularizări / solduri")
    info_ids = fields.One2many("gt.d300.info", "declaration_id", string="Informații suplimentare")
    previous_id = fields.Many2one("gt.anaf.d300", check_company=True, string="Revizia anterioară", readonly=True)
    data = fields.Json("Calcul și documente", readonly=True, copy=False)
    source_hash = fields.Char("Amprenta surselor", readonly=True, copy=False)
    generated_at = fields.Datetime("Calculat la", readonly=True, copy=False)
    state = fields.Selection([("draft", "În lucru"), ("blocked", "Date de corectat"),
        ("calculated", "Calculat"), ("xml", "XML generat, nevalidat ANAF"),
        ("valid", "Validat ANAF"), ("warnings", "Atenționări ANAF"), ("invalid", "Respins ANAF"),
        ("pdf", "PDF ANAF generat")], default="draft", readonly=True, copy=False)
    checks = fields.Text("Verificări", readonly=True, copy=False)
    duk_log = fields.Text("Rezultat ANAF", readonly=True, copy=False)
    xsd_log = fields.Text("Verificare XSD", readonly=True, copy=False)
    validated_at = fields.Datetime("Validat la", readonly=True, copy=False)
    validated_hash = fields.Char("SHA256 XML validat", readonly=True, copy=False)
    runtime_status = fields.Text("Disponibilitate validator", compute="_runtime_status")
    xml_file = fields.Binary("XML", readonly=True, attachment=False, copy=False)
    xml_name = fields.Char(readonly=True, copy=False)
    pdf_file = fields.Binary("PDF ANAF", readonly=True, attachment=False, copy=False)
    pdf_name = fields.Char(readonly=True, copy=False)
    csv_file = fields.Binary(readonly=True, attachment=False, copy=False)
    csv_name = fields.Char(readonly=True, copy=False)
    _outputs = {"data", "source_hash", "generated_at", "state", "checks", "duk_log", "xsd_log",
                "validated_at", "validated_hash", "xml_file", "xml_name", "pdf_file", "pdf_name", "csv_file", "csv_name"}

    @api.depends("company_id", "year", "month", "period_type")
    def _name_compute(self):
        for rec in self:
            rec.name = f"D300 · {rec.month:02d}/{rec.year} · {rec.period_type} · {rec.company_id.name}"

    @api.depends("year", "month", "period_type")
    def _dates(self):
        for rec in self:
            try:
                rec.date_from, rec.date_to = calc.period(rec.year, rec.month, rec.period_type)
            except ValueError:
                rec.date_from = rec.date_to = False

    def _runtime_status(self):
        for rec in self:
            rec.runtime_status = "\n".join(runtime.readiness(*rec._runtime())[1]) or "Validator D300 și Java disponibile; executați validarea."

    def _runtime(self):
        return resolve_duk_dir(self.env, "gt_d300.duk_dir", "d300"), resolve_java(self.env)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self._outputs.intersection(vals):
                raise AccessError("Starea și rezultatele sunt calculate pe server.")
            vals.update({key: False for key in self._outputs})
            vals["state"] = "draft"
        return super().create(vals_list)

    def write(self, vals):
        if self._outputs.intersection(vals):
            raise AccessError("Starea și rezultatele sunt calculate pe server.")
        if "company_id" in vals and any(r.company_id.id != vals["company_id"] and (r.adjustment_ids or r.info_ids) for r in self):
            raise UserError("Creați o declarație nouă pentru altă firmă; există regularizări asociate.")
        result = super().write(vals)
        self._invalidate()
        return result

    def _invalidate(self):
        if self:
            self.check_access("write")
            super(Declaration, self).write({**{k: False for k in self._outputs}, "state": "draft"})

    def _scope(self):
        self.ensure_one()
        self.check_access("write")
        if self.company_id not in self.env.companies:
            raise AccessError("Firma nu este autorizată în sesiunea curentă.")
        if self.company_id.currency_id.name != "RON" or self.company_id.country_id.code != "RO":
            raise UserError("D300 necesită firmă din România cu moneda contabilă RON.")
        try:
            calc.period(self.year, self.month, self.period_type)
        except ValueError as exc:
            raise UserError(str(exc)) from exc
        if not 0 <= self.prorata <= 100:
            raise UserError("Pro-rata trebuie să fie între 0 și 100.")

    def action_standard_mappings(self):
        self._scope()
        count = self.env["gt.d300.mapping"].seed_standard(self.company_id)
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": "Încadrări standard", "message": f"{count} încadrări adăugate. Taxele speciale se configurează în ANAF → Încadrări D300.",
            "type": "info", "sticky": True}}

    def action_prepare_identity(self):
        self._scope()
        bank = self.env["res.partner.bank"].search([("partner_id", "=", self.company_id.partner_id.id)], limit=1)
        vals = {}
        if bank:
            vals.update(bank_name=bank.bank_id.name or "", bank_account=bank.acc_number or "")
        self.write(vals)
        return True

    def _identity(self):
        partner = self.company_id.partner_id
        address = ", ".join(filter(None, [partner.street, partner.street2, partner.city,
                                          partner.state_id.name, partner.zip]))
        return {
            "an": self.year, "luna": self.month, "tip_decont": self.period_type,
            "cui": (self.company_id.vat or "").upper().removeprefix("RO").strip(),
            "den": self.company_id.name, "adresa": address, "telefon": partner.phone or "",
            "mail": partner.email or "", "nume_declar": self.signer_last or "",
            "prenume_declar": self.signer_first or "", "functie_declar": self.signer_role or "",
            "caen": self.caen or "", "banca": self.bank_name or "", "cont": self.bank_account or "",
            "pro_rata": f"{self.prorata:.2f}", "temei": self.legal_basis,
            "cuiSuccesor": self.successor_cui or "", "depusReprezentant": int(self.consolidated),
            "bifa_interne": int(self.simplified), "solicit_ramb": "D" if self.refund else "N",
            "bifa_cereale": "D" if self.cereals else "N", "bifa_mob": "D" if self.mobiles else "N",
            "bifa_disp": "D" if self.chips else "N", "bifa_cons": "D" if self.consoles else "N",
            "nr_evid": calc.payment_reference(self.year, self.month, self.period_type),
        }

    def _build(self):
        self._scope()
        report = self.with_company(self.company_id)
        errors, contributions, source_rows, excluded = [], [], [], []
        mappings = report.env["gt.d300.mapping"].search([("company_id", "=", self.company_id.id)])
        rules = {(r.tax_id.id, r.kind): r for r in mappings}
        info = {k: 0 for k in calc.INFO}
        since6 = self.date_to.replace(day=1) - relativedelta(months=5)
        if self.period_type == "T":
            since6 = self.date_from - relativedelta(months=3)
        for kind in ("purchase", "sale"):
            journal = report.env["gt.ro.vat.journal"].create({"company_id": self.company_id.id,
                "kind": kind, "date_from": self.date_from, "date_to": self.date_to})
            journal.action_refresh()
            data = journal.data
            errors.extend(data["warnings"])
            for item in data["rows"]:
                move = report.env["account.move"].browse(item["move_id"])
                rule = rules.get((item.get("tax_id"), kind))
                item = dict(item, kind=kind, row=rule.row_code if rule else "")
                source_rows.append(item)
                if not rule:
                    errors.append(f"{move.name}: încadrare D300 absentă pentru {item['category']} ({kind}).")
                    continue
                row = rule.row_code
                base = item["paid_base"] if item["cash_basis"] else item["base"]
                tax = item["eligible"] + item["nondeductible"] if item["cash_basis"] else item["vat"]
                eligible = item["eligible"]
                # CABA amounts and bases at the payment exchange rate.
                if item["cash_basis"] and move.currency_id != self.company_id.currency_id:
                    caba = move.tax_cash_basis_created_move_ids.filtered(
                        lambda m: m.state == "posted" and self.date_from <= m.date <= self.date_to)
                    prefix = "4426" if kind == "purchase" else "4427"
                    base = 0
                    for entry in caba:
                        lines = entry.line_ids.filtered(lambda l: l.tax_line_id.id == item["tax_id"]
                            and (l.account_id.code or "").startswith(prefix))
                        if lines:
                            base += max(lines.mapped("tax_base_amount"), key=abs) * (1 if move.is_purchase_document(True) else -1)
                    if item["nondeductible"]:
                        errors.append(f"{move.name}: TVA la încasare în valută cu limitare de deducere necesită verificare distinctă.")
                if row in ("9", "10", "11", "24", "25"):
                    expected = {"9": 21, "10": 11, "11": 9, "24": 21, "25": 11}[row]
                    if rule.tax_id.amount != expected or any(
                        (line.account_id.code or "").startswith("4427") for line in move.line_ids
                        if move.is_purchase_document(True) and line.tax_line_id):
                        errors.append(f"{move.name}: taxă incompatibilă cu rândul standard {row}; verificați taxarea inversă/cota.")
                    if abs(tax - base * expected / 100) > max(2, abs(base) / 100):
                        errors.append(f"{move.name}: baza și TVA nu corespund cotei rândului {row}; verificați repartizarea taxei.")
                if tax and not calc.BY_ROW[row][3]:
                    errors.append(f"{move.name}: TVA nenulă pe un rând fără coloană TVA ({row}).")
                if kind == "purchase" and (abs(eligible) > abs(tax) + .02 or eligible * tax < -.01):
                    errors.append(f"{move.name}: deducerea depășește TVA brută sau are semn incompatibil.")
                if item.get("manual") and not rule.note:
                    errors.append(f"{move.name}: nota manuală necesită justificarea încadrării.")
                contributions.append({"row": row, "base": base if calc.BY_ROW[row][2] else 0,
                    "tax": (eligible if row in ("33", "34") else tax) if calc.BY_ROW[row][3] else 0,
                    "eligible": eligible, "prorata": rule.prorata, "move_id": move.id,
                    "document": move.name, "partner": item["partner"], "date": item["date"],
                    "kind": kind, "tax_id": rule.tax_id.id, "source_line_ids": item.get("source_line_ids", []),
                    "source": "contabilitate"})
                if item["cash_basis"]:
                    suffix = "b" if kind == "purchase" else "a"
                    info["valoare_" + suffix] += item["pending_base"]
                    info["tva_" + suffix] += item["pending_vat"]
                    if fields.Date.to_date(item["invoice_date"]) >= since6:
                        info["valoare_" + suffix + "1"] += item["pending_base"]
                        info["tva_" + suffix + "1"] += item["pending_vat"]
            excluded.append({"kind": kind, "count": data["excluded_notes"]})
            journal.unlink()
        adjustments = [{"row": a.row_code, "base": a.base, "tax": a.tax, "eligible": a.eligible,
                        "reason": a.reason, "evidence": a.evidence, "source": "regularizare"}
                       for a in self.adjustment_ids]
        for extra in self.info_ids:
            info[extra.code] += extra.value
        try:
            values, attrs = calc.calculate(contributions, adjustments, self.prorata, info)
        except ValueError as exc:
            raise UserError(str(exc)) from exc
        identity = self._identity()
        required = ("cui", "den", "adresa", "nume_declar", "prenume_declar", "functie_declar", "caen", "banca", "cont")
        for key in required:
            if not identity[key]:
                errors.append("Identificare incompletă: " + key)
        if not re.fullmatch(r"\d{2,10}", identity["cui"]):
            errors.append("CUI trebuie să conțină 2–10 cifre, fără prefix RO.")
        else:
            digits = identity["cui"]
            check = sum(int(a) * int(b) for a, b in zip(digits[:-1].zfill(9), "753217532")) * 10 % 11
            if (0 if check == 10 else check) != int(digits[-1]):
                errors.append("Cifra de control CUI este incorectă.")
        if not re.fullmatch(r"\d{4}", identity["caen"]):
            errors.append("CAEN trebuie să conțină 4 cifre.")
        if not self.vat_registered:
            errors.append("Confirmați înregistrarea în scopuri de TVA pentru perioada aleasă.")
        if not self.balances_reviewed:
            errors.append("Verificați și confirmați soldurile reportate, plățile și deciziile fiscale.")
        if not self.special_reviewed:
            errors.append("Verificați și confirmați informațiile suplimentare și situațiile speciale.")
        if self.consolidated:
            errors.append("Consolidarea grupului fiscal nu este implementată; acest decont cuprinde doar firma selectată.")
        if values["38"]["tax"] and values["41"]["tax"]:
            errors.append("Soldurile precedente de plată și negativ nu pot fi completate simultan.")
        for code in ("38", "39", "41", "42"):
            if values[code]["tax"] < 0:
                errors.append(f"Soldul rândului {code} nu poate fi negativ.")
        if self.refund and values["45"]["tax"] < 5000:
            errors.append("Rambursarea necesită sold negativ de minimum 5.000 lei.")
        if self.simplified and any(values[str(n)][k] for n in list(range(1, 9)) + list(range(20, 24)) for k in ("base", "tax")):
            errors.append("Decontul simplificat conține operațiuni intracomunitare/externe.")
        for sale, buy in (("5", "20"), ("5.1", "20.1"), ("6", "21"), ("7", "22"), ("7.1", "22.1"),
                          ("8", "23"), ("12", "26"), ("12.1", "26.1"), ("12.2", "26.2")):
            if values[sale] != values[buy]:
                errors.append(f"Taxare inversă: rândurile {sale}/{buy} nu coincid (bază și TVA brută).")
        for k, v in info.items():
            if v < 0:
                errors.append("Indicator suplimentar negativ: " + calc.INFO[k])
        for key in ("valoare_a", "tva_a", "valoare_b", "tva_b"):
            if info[key + "1"] > info[key] + .01:
                errors.append("Indicatorul ultimelor 6 luni depășește soldul total: " + calc.INFO[key])
        # Ledger reconciliation uses turnover before VAT closing and exposes exclusions.
        ledger = {}
        for prefix, sign in (("4426", 1), ("4427", -1), ("4423", -1), ("4424", 1)):
            lines = report.env["account.move.line"].search([
                ("company_id", "=", self.company_id.id), ("parent_state", "=", "posted"),
                ("account_id.code", "=like", prefix + "%"), ("date", "<=", self.date_to)])
            ledger[prefix] = {"opening": sum(l.balance for l in lines if l.date < self.date_from) * sign,
                "debit": sum(l.debit for l in lines if l.date >= self.date_from),
                "credit": sum(l.credit for l in lines if l.date >= self.date_from),
                "closing": sum(lines.mapped("balance")) * sign}
            if prefix in ("4426", "4427"):
                active = lines.filtered(lambda l: l.date >= self.date_from and not (
                    l.move_id.move_type == "entry" and not l.move_id.tax_cash_basis_origin_move_id and l.gt_vat_journal_exclude))
                actual = sum(active.mapped("balance")) * sign
                kind = "purchase" if prefix == "4426" else "sale"
                extracted = sum(item["eligible"] for item in source_rows if item["kind"] == kind)
                ledger[prefix].update(before_closing=actual, extracted=extracted, difference=round(actual - extracted, 2))
                if abs(actual - extracted) > .05:
                    errors.append(f"Control {prefix}: diferență {actual - extracted:.2f} lei între contabilitate și documentele preluate.")
        # Detect any changed/reclassified source, including excluded lines and tax setup.
        relevant = report.env["account.move.line"].search([
            ("company_id", "=", self.company_id.id), ("parent_state", "=", "posted"), ("date", "<=", self.date_to)])
        freshness = [(l.id, str(l.write_date), l.balance, l.tax_ids.ids, l.tax_line_id.id) for l in relevant]
        source = {"rows": source_rows, "contributions": contributions, "adjustments": adjustments,
                  "info": info, "identity": identity, "ledger": ledger, "freshness": freshness,
                  "rules": [(r.id, r.tax_id.id, r.kind, r.row_code, r.prorata, r.tax_id.amount, str(r.write_date)) for r in mappings],
                  "confirmed": [self.vat_registered, self.balances_reviewed, self.special_reviewed]}
        return {"rows": [{"code": code, "label": label, **values[code], "has_base": bool(b),
                          "has_tax": bool(t), "calculated": code in calc.CALCULATED, "parent": parent}
                         for code, label, b, t, parent in calc.ROWS],
                "contributions": contributions, "adjustments": adjustments, "sources": source_rows,
                "info": info, "ledger": ledger, "excluded": excluded,
                "errors": sorted(set(errors)), "identity": identity, "attrs": attrs,
                "hash": calc.digest(source), "company": self.company_id.name,
                "period": f"{self.date_from} — {self.date_to}", "profile": "OPANAF 174/2026 · XML v12"}

    def action_calculate(self):
        data = self._build()
        super().write({**{k: False for k in self._outputs}, "data": data,
            "source_hash": data["hash"], "generated_at": fields.Datetime.now(),
            "state": "blocked" if data["errors"] else "calculated",
            "checks": "\n".join(data["errors"]) or "Verificări locale trecute. Validarea oficială ANAF se execută separat."})
        return True

    def _fresh(self):
        self._scope()
        if not self.data:
            raise UserError("Apăsați Actualizează din contabilitate.")
        current = self._build()
        if current["hash"] != self.source_hash:
            raise UserError("Datele sursă/configurația s-au modificat. Recalculați declarația înainte de export.")
        if current["errors"]:
            raise UserError("Export blocat:\n" + "\n".join(current["errors"][:30]))
        return current

    def _download(self, field, name):
        return {"type": "ir.actions.act_url", "url":
                f"/web/content/gt.anaf.d300/{self.id}/{field}/{name}?download=true", "target": "download"}

    def action_xml(self):
        data = self._fresh()
        raw = calc.xml_bytes(data["identity"], data["attrs"])
        if (self.state in ("valid", "pdf") and self.validated_hash == runtime.sha(raw)
                and self.xml_file and base64.b64decode(self.xml_file) == raw):
            return self._download("xml_file", self.xml_name)
        schema_result = runtime.validate_schema(raw, self._runtime()[0])
        if schema_result["status"] == "invalid":
            super().write({"xsd_log": schema_result["report"], "state": "invalid"})
            return True
        name = f"D300_{self.year}_{self.month:02d}_{self.id}_NEVALIDAT.xml"
        super().write({"xml_file": base64.b64encode(raw), "xml_name": name,
            "pdf_file": False, "pdf_name": False, "validated_hash": False, "validated_at": False,
            "state": "xml", "xsd_log": schema_result["report"], "duk_log": False})
        return self._download("xml_file", name)

    def action_validate(self):
        return self._run_anaf(False)

    def action_pdf(self):
        return self._run_anaf(True)

    def _run_anaf(self, make_pdf):
        data = self._fresh()
        raw = calc.xml_bytes(data["identity"], data["attrs"])
        xsd = runtime.validate_schema(raw, self._runtime()[0])
        if xsd["status"] == "invalid":
            super().write({"state": "invalid", "xsd_log": xsd["report"], "pdf_file": False})
            return True
        result = runtime.run(raw, *self._runtime(), make_pdf=make_pdf)
        name = f"D300_{self.year}_{self.month:02d}_{self.id}"
        ok = result["status"] == "valid"
        super().write({"state": ("pdf" if make_pdf else "valid") if ok else (
            result["status"] if result["status"] in ("invalid", "warnings") else "xml"),
            "xml_file": base64.b64encode(raw), "xml_name": name + (".xml" if ok else "_NEVALIDAT.xml"),
            "pdf_file": base64.b64encode(result["pdf"]) if result.get("pdf") else False,
            "pdf_name": name + ".pdf" if result.get("pdf") else False,
            "duk_log": result["report"], "xsd_log": xsd["report"],
            "validated_at": fields.Datetime.now() if ok else False,
            "validated_hash": runtime.sha(raw) if ok else False})
        return self._download("pdf_file", self.pdf_name) if result.get("pdf") else True

    def action_csv(self):
        self._scope()
        if not self.data:
            raise UserError("Calculați declarația.")
        output = StringIO()
        writer = csv.writer(output, delimiter=";")
        def safe(v):
            s = str(v)
            return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s
        writer.writerow(["D300 - SITUAȚIE DE LUCRU", safe(self.company_id.name), self.data["period"]])
        writer.writerow(["Rând", "Indicator", "Bază lei", "TVA lei"])
        for r in self.data["rows"]:
            writer.writerow([r["code"], r["label"], r["base"] if r["has_base"] else "", r["tax"] if r["has_tax"] else ""])
        writer.writerow(["DOCUMENTE SURSE"])
        writer.writerow(["Rând", "Document", "Data", "Partener", "Bază", "TVA", "Dedusă"])
        for c in self.data["contributions"]:
            writer.writerow([c["row"], safe(c["document"]), c["date"], safe(c["partner"]), c["base"], c["tax"], c["eligible"]])
        for error in self.data["errors"]:
            writer.writerow(["BLOCAJ", safe(error)])
        name = f"D300_{self.year}_{self.month:02d}_situatie_lucru.csv"
        super().write({"csv_file": base64.b64encode(output.getvalue().encode("utf-8-sig")), "csv_name": name})
        return self._download("csv_file", name)

    def action_revision(self):
        self._scope()
        new = self.copy({"previous_id": self.id,
            "adjustment_ids": [Command.create({k: a[k] for k in ("row_code", "base", "tax", "eligible", "reason", "evidence")}) for a in self.adjustment_ids],
            "info_ids": [Command.create({k: a[k] for k in ("code", "value", "reason")}) for a in self.info_ids]})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": new.id, "view_mode": "form", "target": "current"}

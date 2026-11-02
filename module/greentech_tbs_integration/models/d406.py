"""Local safeguards around the supplier's periodic SAF-T exporter."""
import hashlib
from calendar import monthrange

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.tbs_saft_d406.d406 import sanitize, registration

OPTIONS = {"company_id", "date_from", "date_to", "declaration_type", "segment_index", "total_segments",
           "gt_contact_first", "gt_contact_last"}
OUTPUTS = {"state", "attachment_id", "xsd_valid", "validation_log",
           "gt_xml_sha256", "gt_duk_valid", "gt_pdf_id"}


class Export(models.TransientModel):
    _inherit = "l10n.ro.d406.export.wizard"

    gt_xml_sha256 = fields.Char(readonly=True)
    gt_duk_valid = fields.Boolean(string="Validat cu DUK local", readonly=True)
    gt_pdf_id = fields.Many2one("ir.attachment", readonly=True)
    gt_contact_first = fields.Char("Prenume persoană de contact")
    gt_contact_last = fields.Char("Nume persoană de contact")

    @api.model_create_multi
    def create(self, vals_list):
        if any(OUTPUTS.intersection(vals) for vals in vals_list):
            raise AccessError("Rezultatele D406 se obțin numai prin generare și validare.")
        return super().create([dict(vals, **{key: "draft" if key == "state" else False
                                           for key in OUTPUTS}) for vals in vals_list])

    def write(self, vals):
        if OUTPUTS.intersection(vals):
            raise AccessError("Rezultatele D406 nu se editează manual.")
        if OPTIONS.intersection(vals):
            vals = dict(vals, state="draft", attachment_id=False, xsd_valid=False,
                        validation_log=False, gt_xml_sha256=False, gt_duk_valid=False, gt_pdf_id=False)
        return super().write(vals)

    def _save_result(self, vals):
        return super().write(vals)

    def _reopen(self):
        return dict(super()._reopen(), name="D406 — SAF-T periodic")

    def _scope(self):
        self.ensure_one()
        self.check_access("write")
        if not self.env.user.has_group("account.group_account_manager"):
            raise AccessError("Exportul D406 necesită drepturi de contabil.")
        if self.company_id not in self.env.companies:
            raise AccessError("Firma declarației nu se află între firmele active.")
        return self.with_company(self.company_id).with_context(allowed_company_ids=[self.company_id.id])

    def _period_errors(self):
        if not self.date_from or not self.date_to:
            return ["Completați perioada."]
        start, end = self.date_from, self.date_to
        months = 3 if self.declaration_type in ("T", "NT") else 1
        if (start.day != 1 or start.year != end.year or end.month != start.month + months - 1
                or end.day != monthrange(end.year, end.month)[1]
                or (months == 3 and start.month not in (1, 4, 7, 10))):
            return ["Selectați o lună completă sau un trimestru calendaristic complet, conform tipului declarației."]
        if self.segment_index != 1 or self.total_segments != 1:
            return ["Exportul segmentat nu este implementat. Folosiți un singur segment (1 din 1)."]
        return []

    def _collect_problems(self):
        scoped = self._scope()
        problems = self._period_errors()
        company = self.company_id
        if company.country_id.code != "RO" or company.currency_id.name != "RON":
            problems.append("Integrarea locală necesită o firmă din România cu moneda RON.")
        for label, value in (("CUI", company.vat), ("localitate", company.city),
                             ("țară", company.country_id), ("telefon", company.phone),
                             ("bază contabilă SAF-T", company.l10n_ro_d406_tax_accounting_basis)):
            if not value:
                problems.append("Lipsește la firmă: " + label + ".")
        if not self.gt_contact_first or not self.gt_contact_last:
            problems.append("Completați numele și prenumele persoanei de contact a declarației.")
        if not company.partner_id.bank_ids:
            problems.append("Completați un cont bancar al firmei.")
        if problems:
            return problems
        lines = scoped.env["account.move.line"].search([
            ("company_id", "=", company.id), ("parent_state", "=", "posted"),
            ("date", ">=", self.date_from), ("date", "<=", self.date_to)])
        historical = scoped.env["account.move.line"].search([
            ("company_id", "=", company.id), ("parent_state", "=", "posted"),
            ("date", "<=", self.date_to)])
        accounts = historical.account_id
        if historical.filtered(lambda l: not l.partner_id and l.account_id.account_type in ("asset_receivable", "liability_payable")):
            problems.append("Există înregistrări pe conturi de clienți/furnizori fără partener. Completați partenerul în contabilitate.")
        unmapped = accounts.filtered(lambda a: a.l10n_ro_d406_mapping_status in ("unresolved", "not_numeric"))
        if unmapped:
            problems.append("Conturi utilizate fără cod ANAF: " + ", ".join(unmapped.mapped("code")[:30]))
        taxes = lines.tax_ids | lines.tax_line_id
        unmapped = taxes.filtered(lambda t: not t.l10n_ro_d406_tax_type_id or not t.l10n_ro_d406_tax_code_id)
        if unmapped:
            problems.append("Taxe utilizate fără încadrare SAF-T: " + ", ".join(unmapped.mapped("name")[:30]))
        for tax in taxes - unmapped:
            code = tax.l10n_ro_d406_tax_code_id
            if code.vat_rate and abs(code.vat_rate - tax.amount) > 0.001:
                problems.append(f"Cota taxei {tax.name} nu corespunde codului SAF-T {code.code}.")
            if code.date_start and code.date_start > self.date_from or code.date_end and code.date_end < self.date_to:
                problems.append(f"Codul SAF-T {code.code} pentru {tax.name} nu acoperă întreaga perioadă.")
            if tax.amount_type != "percent" or tax.amount < 0:
                problems.append(f"Taxa {tax.name}: calculul SAF-T pentru taxe compuse/fixe/negative nu este verificat.")
        invoices = lines.move_id.filtered(lambda m: m.move_type != "entry")
        foreign = invoices.filtered(lambda m: m.currency_id != company.currency_id)
        if foreign:
            problems.append("Exportul facturilor în valută necesită adaptare suplimentară: " + ", ".join(foreign.mapped("name")[:10]))
        partners = invoices.partner_id.commercial_partner_id | historical.filtered(
            lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")).partner_id
        missing = partners.filtered(lambda p: not p.city or not p.country_id)
        if missing:
            problems.append("Completați localitatea și țara partenerilor: " + ", ".join(missing.mapped("display_name")[:20]))
        # The supplier groups customer/supplier balances into one account per
        # partner. Refuse ambiguous balances instead of assigning them to MIN(id).
        seen = {}
        for line in historical.filtered(lambda l: l.partner_id and l.account_id.account_type in ("asset_receivable", "liability_payable")):
            seen.setdefault((line.partner_id.id, line.account_id.account_type), set()).add(line.account_id.id)
        ambiguous = {key[0] for key, values in seen.items() if len(values) > 1}
        if ambiguous:
            names = scoped.env["res.partner"].browse(sorted(ambiguous)).mapped("display_name")
            problems.append("Solduri pe mai multe conturi pentru același partener; exportul necesită adaptare: " + ", ".join(names[:15]))
        return problems

    def action_check(self):
        self._scope()
        problems = self._collect_problems()
        self._save_result({"validation_log": "\n".join(problems) if problems else
                           "Verificările preliminare au trecut. Generați XML și rulați validarea DUK."})
        return self._reopen()

    def _generate_xml(self):
        scoped = self._scope()
        problems = scoped._collect_problems()
        if problems:
            raise UserError("\n".join(problems))
        scoped = scoped.with_context(gt_d406_contact=(self.gt_contact_first, self.gt_contact_last))
        return super(Export, scoped)._generate_xml()

    def action_generate(self):
        raw = self._generate_xml()
        valid, messages = self.env["l10n.ro.d406.validator"].validate_xsd(raw)
        if not valid:
            self._save_result({"state": "draft", "attachment_id": False, "gt_pdf_id": False,
                               "gt_xml_sha256": False, "gt_duk_valid": False, "xsd_valid": False,
                               "validation_log": "XML respins la verificarea structurală:\n" + "\n".join(messages[:100])})
            return self._reopen()
        attachment = self.env["ir.attachment"].create({
            "name": self._filename(), "raw": raw, "mimetype": "application/xml",
            "res_model": self._name, "res_id": self.id})
        self._save_result({"state": "done", "attachment_id": attachment.id,
                           "gt_xml_sha256": hashlib.sha256(raw).hexdigest(),
                           "gt_duk_valid": False, "gt_pdf_id": False, "xsd_valid": True,
                           "validation_log": "Structura XSD verificată pe copia cu namespace adaptat. "
                           "XML generat pentru verificare; validarea DUK este încă necesară."})
        return self._reopen()

    def _current_xml(self):
        self._scope()
        if not self.attachment_id or not self.gt_xml_sha256:
            raise UserError("Generați mai întâi declarația.")
        raw = self.attachment_id.raw
        if (self.attachment_id.res_model != self._name or self.attachment_id.res_id != self.id
                or hashlib.sha256(raw).hexdigest() != self.gt_xml_sha256
                or hashlib.sha256(self._generate_xml()).hexdigest() != self.gt_xml_sha256):
            raise UserError("Datele sau fișierul s-au schimbat. Regenerați și revalidați D406.")
        return raw

    def action_validate_duk(self):
        raw = self._current_xml()
        result = self.env["anaf.duk.validator"].validate(
            raw, "D406", year=self.date_to.year, month=self.date_to.month)
        self._save_result({"gt_duk_valid": bool(result.get("success")), "gt_pdf_id": False,
                           "validation_log": result.get("message") or result.get("errors")})
        return self._reopen()

    def action_download(self):
        self._current_xml()
        return super().action_download()

    def action_generate_pdf(self):
        raw = self._current_xml()
        result = self.env["anaf.duk.validator"].generate_pdf(
            raw, "D406", year=self.date_to.year, month=self.date_to.month)
        if not result.get("success"):
            self._save_result({"gt_duk_valid": False, "gt_pdf_id": False,
                               "validation_log": result.get("errors")})
            return self._reopen()
        pdf = self.env["ir.attachment"].create({
            "name": self._filename().replace(".xml", ".pdf"), "raw": result["pdf_data"],
            "mimetype": "application/pdf", "res_model": self._name, "res_id": self.id})
        self._save_result({"gt_duk_valid": True, "gt_pdf_id": pdf.id,
                           "validation_log": result["message"]})
        return self._reopen()

    def action_download_pdf(self):
        self._current_xml()
        if not self.gt_pdf_id or not self.gt_duk_valid:
            raise UserError("Generați PDF cu validatorul local.")
        return {"type": "ir.actions.act_url", "url": f"/web/content/{self.gt_pdf_id.id}?download=true", "target": "self"}


class Generator(models.AbstractModel):
    _inherit = "l10n.ro.d406.generator"

    def _build_movement_type_table(self, parent, context):
        # Periodic export has no MovementOfGoods entries. Odoo picking-type IDs
        # are not ANAF movement nomenclature codes and must never be emitted.
        return

    def _partner_saft_id(self, partner, context, is_customer=True):
        if not partner:
            # ANAF FAQ: internal entries use 00 + the reporting company's CUI.
            return "00" + sanitize.cui(context["company_registration"])
        identifier = registration.partner_registration_number(
            self._partner_identity(partner), is_customer=is_customer)
        if not identifier:
            raise UserError("Partener fără identificator SAF-T: " + partner.display_name)
        return identifier

    def _period_taxes(self, context):
        taxes = super()._period_taxes(context)
        tax_lines = self.env["account.move.line"].search([
            ("company_id", "=", context["company"].id), ("parent_state", "=", "posted"),
            ("date", ">=", context["date_from"]), ("date", "<=", context["date_to"]),
            ("tax_line_id", "!=", False)])
        return taxes | tax_lines.tax_line_id

    def _add_tax_information(self, parent, line, context):
        taxes = line.tax_ids | line.tax_line_id
        if not taxes:
            return super()._add_tax_information(parent, line, context)
        for tax in taxes:
            if not tax.l10n_ro_d406_tax_type_id or not tax.l10n_ro_d406_tax_code_id:
                raise UserError("Taxă fără încadrare SAF-T: " + tax.name)
            node = parent.child("TaxInformation")
            node.add_required("TaxType", tax.l10n_ro_d406_tax_type_id.code)
            node.add_required("TaxCode", tax.l10n_ro_d406_tax_code_id.code)
            node.add("TaxPercentage", sanitize.monetary(tax.amount))
            base = abs(line.tax_base_amount) if line.tax_line_id else abs(line.balance)
            node.add("TaxBase", sanitize.monetary(base))
            self._add_amount(node, "TaxAmount", line.company_id.currency_id.round(
                self._line_tax_amount(line, tax)), context)

    def _build_invoice_line(self, parent, line, index, context):
        super()._build_invoice_line(parent, line, index, context)
        node = parent.element[-1]
        amount = line.credit if line.credit else line.debit
        node.find("{*}DebitCreditIndicator").text = "C" if line.credit else "D"
        for tag in ("Amount", "CurrencyAmount"):
            node.find("{*}InvoiceLineAmount/{*}" + tag).text = sanitize.monetary(amount)

    def _add_header_contact(self, parent, partner, company):
        first, last = self.env.context.get("gt_d406_contact", ("", ""))
        if not first or not last:
            raise UserError("Lipsește persoana de contact a declarației D406.")
        contact = parent.child("Contact")
        person = contact.child("ContactPerson")
        person.add_required("FirstName", sanitize.text(first, 100))
        person.add_required("LastName", sanitize.text(last, 100))
        contact.add_required("Telephone", sanitize.text(partner.phone, 20))
        contact.add("Email", sanitize.text(partner.email, 254))
        return contact

    def _add_line_amount(self, parent, line, context):
        # Preserve negative debit/credit on Romanian red-storno entries.
        is_credit = bool(line.credit)
        amount = line.credit if is_credit else line.debit
        currency = line.currency_id or context["company"].currency_id
        foreign = currency != context["company"].currency_id
        self._add_amount(parent, "CreditAmount" if is_credit else "DebitAmount", amount, context,
                         currency=currency, currency_amount=(-line.amount_currency if is_credit else line.amount_currency) if foreign else amount,
                         rate=abs(line.amount_currency / line.balance) if foreign and line.balance else 1.0)

    def _add_document_header_totals(self, parent, moves, context):
        lines = moves.mapped("line_ids")
        if moves and all(m.move_type != "entry" for m in moves):
            lines = moves.mapped("invoice_line_ids").filtered(lambda l: l.display_type in (False, "product"))
        parent.add_required("NumberOfEntries", str(len(moves)))
        parent.add_required("TotalDebit", sanitize.monetary(sum(lines.mapped("debit"))))
        parent.add_required("TotalCredit", sanitize.monetary(sum(lines.mapped("credit"))))

    def _invoice_tax_totals(self, move):
        # Negative advance regularizations reduce the base/tax in the same invoice.
        sign = -1 if move.move_type in ("out_invoice", "in_refund") else 1
        totals = {}
        for line in self._invoice_product_lines(move):
            for tax in line.tax_ids:
                if tax.l10n_ro_d406_tax_type_id and tax.l10n_ro_d406_tax_code_id:
                    base, amount = totals.get(tax, (0.0, 0.0))
                    signed_base = line.balance * sign
                    totals[tax] = (base + signed_base, amount + move.company_id.currency_id.round(signed_base * tax.amount / 100))
        return [(tax, base, amount) for tax, (base, amount) in totals.items()]

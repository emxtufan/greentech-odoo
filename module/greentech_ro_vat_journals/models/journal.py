import base64
import csv
from collections import defaultdict
from io import StringIO

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from ..services.pdf import render_pdf

AMOUNTS = ("base", "vat", "total", "eligible", "nondeductible",
           "paid", "paid_base", "paid_vat", "unpaid", "pending_base", "pending_vat")
LABELS = ("Bază document", "TVA document", "Total cu TVA", "TVA deductibilă/colectată în perioadă",
          "TVA nedeductibilă în perioadă", "Achitat/încasat în perioadă",
          "Bază achitată în perioadă", "TVA achitată în perioadă",
          "Neachitat la final", "Bază neexigibilă", "TVA neexigibilă")


class MoveLine(models.Model):
    _inherit = "account.move.line"

    gt_vat_journal_exclude = fields.Boolean("Exclude din jurnalele TVA",
        help="Numai pentru note contabile, de exemplu închiderea TVA. Nu exclude facturile.")
    gt_vat_manual_base = fields.Monetary("Bază TVA notă manuală",
        help="Baza în moneda firmei, cu semnul operațiunii. Folosită numai la note fără bază fiscală Odoo.")


class Journal(models.TransientModel):
    _name = "gt.ro.vat.journal"
    _description = "Jurnal cumpărări / vânzări"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name")
    kind = fields.Selection([("purchase", "Jurnal cumpărări"), ("sale", "Jurnal vânzări")],
                            required=True, default="purchase", string="Jurnal")
    company_id = fields.Many2one("res.company", string="Firmă", required=True, default=lambda s: s.env.company)
    date_from = fields.Date("De la", required=True, default=lambda s: fields.Date.today().replace(day=1))
    date_to = fields.Date("Până la", required=True, default=fields.Date.context_today)
    partner_id = fields.Many2one("res.partner", "Furnizor / client")
    deduction = fields.Selection([("all", "Toate"), ("50", "TVA nedeductibilă 50%"),
                                  ("100", "TVA nedeductibilă integral")], default="all", required=True,
                                 string="Filtru cumpărări")
    data = fields.Json(readonly=True)
    generated_at = fields.Datetime("Actualizat la", readonly=True)
    export_file = fields.Binary(readonly=True, attachment=False)
    export_name = fields.Char(readonly=True)
    pdf_file = fields.Binary(readonly=True, attachment=False)
    pdf_name = fields.Char(readonly=True)
    _outputs = {"data", "generated_at", "export_file", "export_name", "pdf_file", "pdf_name"}

    @api.depends("kind")
    def _compute_name(self):
        for record in self:
            record.name = "Jurnal cumpărări" if record.kind == "purchase" else "Jurnal vânzări"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self._outputs.intersection(vals):
                raise AccessError("Rezultatele sunt calculate din contabilitate.")
            vals.update({key: False for key in self._outputs})
        return super().create(vals_list)

    def write(self, vals):
        if self._outputs.intersection(vals):
            raise AccessError("Rezultatele sunt calculate din contabilitate.")
        if {"kind", "company_id", "date_from", "date_to", "partner_id", "deduction"}.intersection(vals):
            vals = dict(vals, **{key: False for key in self._outputs})
        return super().write(vals)

    def _check_scope(self):
        self.ensure_one()
        self.check_access("read")
        if self.company_id not in self.env.companies:
            raise AccessError("Selectați o firmă autorizată.")
        if not self.date_from or not self.date_to or self.date_from > self.date_to:
            raise UserError("Intervalul de raportare nu este valid.")
        if self.company_id.currency_id.name != "RON":
            raise UserError("Aceste jurnale necesită moneda contabilă RON.")

    def _row(self, move, category, **values):
        return {**{key: 0.0 for key in AMOUNTS}, **{
            "move_id": move.id, "document": move.ref or move.name,
            "entry": move.name, "date": str(move.date),
            "invoice_date": str(move.invoice_date or move.date),
            "partner": move.partner_id.name or "Fără partener",
            "vat_number": move.partner_id.vat or "", "category": category,
            "cash_basis": False, "payments": [], "note": "",
        }, **values}

    def _settlements(self, move):
        """Reconstruct settlement at cutoff, not the present-day residual."""
        terms = move.line_ids.filtered(lambda l: l.account_id.account_type in (
            "asset_receivable", "liability_payable"))
        partials = terms.matched_debit_ids | terms.matched_credit_ids
        total_cur = abs(sum(terms.mapped("amount_currency")))
        results = []
        for partial in partials.sorted(lambda p: (p.max_date, p.id)):
            if partial.max_date > self.date_to:
                continue
            debit = partial.debit_move_id in terms
            own = partial.debit_move_id if debit else partial.credit_move_id
            other = partial.credit_move_id if debit else partial.debit_move_id
            if other.move_id.state != "posted":
                continue
            cur_amount = partial.debit_amount_currency if debit else partial.credit_amount_currency
            ratio = abs(cur_amount) / total_cur if total_cur else 0
            results.append({"partial_id": partial.id, "move_id": other.move_id.id,
                "date": str(partial.max_date), "document": other.move_id.name,
                "amount": partial.amount, "ratio": ratio,
                "in_period": self.date_from <= partial.max_date <= self.date_to,
                "kind": "Compensare / stornare" if other.move_id.is_invoice(True) else "Plată / încasare"})
        return results

    def _invoice_rows(self, move, warnings):
        """Use posted tax amounts and bases, including separate reverse-charge sides."""
        purchase = self.kind == "purchase"
        native = move.is_purchase_document(True) if purchase else move.is_sale_document(True)
        sign = 1 if purchase else -1
        prefix = "4426" if purchase else "4427"
        groups = defaultdict(lambda: self.env["account.move.line"])
        for line in move.line_ids.filtered("tax_line_id"):
            if line.tax_line_id.amount == 0:
                continue
            # The purchase reverse-charge output side belongs in the sales journal.
            relevant = (line.account_id.code or "").startswith(prefix)
            if native and line.tax_line_id.tax_exigibility == "on_payment":
                relevant = True
            if relevant:
                groups[line.tax_line_id.id] |= line
        rows = []
        settlements = self._settlements(move)
        fraction = min(1.0, sum(p["ratio"] for p in settlements))
        period_fraction = sum(p["ratio"] for p in settlements if p["in_period"])
        # Tax bases may repeat on split repartitions: each posted tax base is counted once.
        for tax_id, lines in groups.items():
            tax = self.env["account.tax"].browse(tax_id)
            cash = tax.tax_exigibility == "on_payment"
            if cash and move.date < self.date_from and fraction >= 1 - 1e-8 and not period_fraction:
                continue
            if not cash and move.date < self.date_from:
                continue
            vat = sum(lines.mapped("balance")) * sign
            bases = {round(l.tax_base_amount, 2) for l in lines}
            base = max(bases, key=abs, default=0) * (1 if move.is_purchase_document(True) else -1)
            # Some imports preserve the tax accounting but omit the taxable base.
            note = ""
            if not base and vat:
                note = "Baza fiscală lipsește în document; verificați înregistrarea sursă."
                warnings.add(f"{move.name}: {note}")
            sources = move.line_ids.filtered(lambda l: l.display_type == "product"
                and tax in l.tax_ids.flatten_taxes_hierarchy())
            denominator = sum(abs(l.balance) for l in sources)
            nd_fraction = sum(abs(l.balance) * (1 - l.deductible_amount / 100)
                              for l in sources) / denominator if denominator else 0
            overall_nd = nd_fraction
            if self.deduction != "all" and purchase:
                wanted = int(self.deduction) / 100
                selected = sources.filtered(lambda l: abs(1 - l.deductible_amount / 100 - wanted) < 1e-8)
                share = sum(abs(l.balance) for l in selected) / denominator if denominator else 0
                if not share:
                    continue
                base *= share
                vat *= share
                nd_fraction = wanted
            else:
                share = 1
            regime = "TVA la plată/încasare" if cash else "TVA la factură"
            category = f"{tax.name} · {regime}"
            if not native:
                category += " · taxare inversă / TVA colectată din achiziții"
            row = self._row(move, category, base=base, vat=vat, total=base + vat,
                            cash_basis=cash, note=note, tax_id=tax.id,
                            source_line_ids=sources.ids, tax_line_ids=lines.ids)
            if not cash:
                corrections = move.line_ids.filtered(lambda l:
                    l.display_type == "non_deductible_tax_ro"
                    and (l.account_id.code or "").startswith(prefix)
                    and l.name in (tax.name, f"{tax.name} (non-deductible total)")
                    and l.l10n_ro_non_deductible_line_id in sources)
                if self.deduction != "all":
                    eligible = vat * (1 - nd_fraction)
                else:
                    eligible = vat + sum(corrections.mapped("balance")) * sign
                row.update(eligible=eligible, nondeductible=vat - eligible)
                if abs(eligible - vat * (1 - nd_fraction)) > 0.02:
                    warnings.add(f"{move.name}: TVA din contabilitate diferă de deductibilitatea liniilor; verificați contul și taxele nedeductibile.")
            else:
                caba = move.tax_cash_basis_created_move_ids.filtered(
                    lambda m: m.state == "posted" and self.date_from <= m.date <= self.date_to)
                recognized = caba.line_ids.filtered(lambda l:
                    l.tax_line_id == tax and (l.account_id.code or "").startswith(prefix))
                eligible_share = 1
                if self.deduction != "all":
                    eligible_share = share * (1 - nd_fraction) / (1 - overall_nd) if overall_nd < 1 else 0
                eligible = sum(recognized.mapped("balance")) * sign * eligible_share
                row.update(
                    paid=(base + vat) * period_fraction, paid_base=base * period_fraction,
                    paid_vat=vat * period_fraction, eligible=eligible,
                    nondeductible=vat * period_fraction * nd_fraction,
                    unpaid=(base + vat) * (1 - fraction),
                    pending_base=base * (1 - fraction), pending_vat=vat * (1 - fraction),
                    payments=settlements,
                )
                if period_fraction and not caba:
                    warnings.add(f"{move.name}: există decontări, dar lipsesc notele de exigibilitate TVA în perioadă.")
                if move.currency_id == move.company_currency_id and abs(eligible - vat * period_fraction * (1 - nd_fraction)) > 0.02:
                    warnings.add(f"{move.name}: TVA exigibilă contabilizată diferă de proporția decontată/deductibilă; verificați notele de exigibilitate.")
                if move.currency_id != move.company_currency_id:
                    row["note"] = "Baza achitată/neexigibilă la cursul facturii; TVA exigibilă din notele contabile la plată."
            rows.append(row)
        if native and self.date_from <= move.date <= self.date_to and self.deduction == "all":
            # Preserve 0% and absent-tax documents, without inventing a fiscal exemption.
            zero = defaultdict(lambda: self.env["account.move.line"])
            for line in move.line_ids.filtered(lambda l: l.display_type == "product"):
                taxes = line.tax_ids.flatten_taxes_hierarchy()
                if not taxes or all(t.amount == 0 for t in taxes):
                    zero[", ".join(taxes.mapped("name")) or "Fără taxă configurată"] |= line
            for label, lines in zero.items():
                base = sum(lines.mapped("balance")) * sign
                zero_taxes = lines.tax_ids.flatten_taxes_hierarchy()
                rows.append(self._row(move, label, base=base, total=base,
                    tax_id=zero_taxes.id if len(zero_taxes) == 1 else False,
                    source_line_ids=lines.ids, tax_line_ids=[]))
                if label == "Fără taxă configurată":
                    warnings.add(f"{move.name}: fără taxă configurată; verificați încadrarea fiscală, nu se presupune scutirea.")
            if not rows and move.amount_total:
                warnings.add(f"{move.name}: document fără linii fiscale identificabile; verificați importul/configurația taxelor.")
        return rows

    def action_refresh(self):
        self._check_scope()
        report = self.with_company(self.company_id)
        domain = [("company_id", "=", self.company_id.id), ("state", "=", "posted"),
                  ("date", "<=", self.date_to)]
        if self.partner_id:
            domain.append(("partner_id", "child_of", self.partner_id.commercial_partner_id.id))
        # Sales also reads purchase reverse-charge output VAT (4427).
        types = ["in_invoice", "in_refund", "in_receipt"]
        if self.kind == "sale":
            types += ["out_invoice", "out_refund", "out_receipt"]
        moves = report.env["account.move"].search(domain + [("move_type", "in", types)], order="date,id")
        warnings, rows = set(), []
        for move in moves:
            if move.date < self.date_from and not any(t.tax_exigibility == "on_payment" for t in move.line_ids.tax_ids):
                continue
            rows.extend(report._invoice_rows(move, warnings))
        prefix, sign = ("4426", 1) if self.kind == "purchase" else ("4427", -1)
        entries = report.env["account.move"].search(domain + [
            ("move_type", "=", "entry"), ("date", ">=", self.date_from),
            ("tax_cash_basis_origin_move_id", "=", False),
        ], order="date,id")
        excluded = 0
        for move in entries:
            for line in move.line_ids.filtered(lambda l: (l.account_id.code or "").startswith(prefix)):
                if line.gt_vat_journal_exclude:
                    excluded += 1
                    continue
                if self.deduction != "all":
                    continue
                base = line.gt_vat_manual_base
                if not base and line.tax_base_amount:
                    base = abs(line.tax_base_amount) * (1 if line.balance * sign >= 0 else -1)
                vat = line.balance * sign
                note = ""
                if not base and vat:
                    note = "Notă fără bază TVA. Completați baza sau excludeți explicit închiderea TVA."
                    warnings.add(f"{move.name}: {note}")
                category = f"Note {prefix} · {line.tax_line_id.name or 'încadrare de verificat'}"
                rows.append(report._row(move, category, base=base, vat=vat, total=base+vat,
                                        eligible=vat, note=note, tax_id=line.tax_line_id.id,
                                        source_line_ids=[line.id], tax_line_ids=[line.id], manual=True))
        summaries = {}
        for index, row in enumerate(rows):
            row["id"] = index + 1
            for key in AMOUNTS:
                row[key] = self.company_id.currency_id.round(row[key])
            summary = summaries.setdefault(row["category"], dict(
                {"category": row["category"], "count": 0}, **{key: 0.0 for key in AMOUNTS}))
            summary["count"] += 1
            for key in AMOUNTS:
                summary[key] += row[key]
        data = {"rows": rows, "summary": list(summaries.values()),
                "totals": {key: sum(row[key] for row in rows) for key in AMOUNTS},
                "warnings": sorted(warnings), "excluded_notes": excluded,
                "company": self.company_id.name, "kind": self.kind,
                "date_from": str(self.date_from), "date_to": str(self.date_to)}
        super(Journal, self).write({"data": data, "generated_at": fields.Datetime.now(),
                                    "export_file": False, "export_name": False, "pdf_file": False, "pdf_name": False})
        return True

    def _ensure_data(self):
        self._check_scope()
        if not self.data:
            raise UserError("Apăsați Actualizează jurnalul.")

    def action_pdf(self):
        self._ensure_data()
        raw = render_pdf(self.data, self.company_id.vat or "", str(self.generated_at),
                         self.partner_id.name or "", self.deduction)
        name = f"Jurnal_{self.kind}_{self.date_from}_{self.date_to}.pdf"
        super(Journal, self).write({"pdf_file": base64.b64encode(raw), "pdf_name": name})
        return {"type": "ir.actions.act_url", "url":
                f"/web/content/gt.ro.vat.journal/{self.id}/pdf_file/{name}?download=true", "target": "download"}

    def action_csv(self):
        self._ensure_data()
        output = StringIO()
        writer = csv.writer(output, delimiter=";")
        def safe(value):
            value = str(value)
            return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value
        writer.writerow([self.name, safe(self.company_id.name), str(self.date_from), str(self.date_to), "RON"])
        writer.writerow(["Data contabilă", "Data document", "Document", "Partener", "CUI", "Categorie",
                         *LABELS, "Observații"])
        for row in self.data["rows"]:
            writer.writerow([safe(row[k]) for k in ("date", "invoice_date", "document", "partner", "vat_number", "category")]
                            + [f"{row[k]:.2f}".replace(".", ",") for k in AMOUNTS] + [safe(row["note"])])
        writer.writerow(["TOTAL", "", "", "", "", ""] + [
            f"{self.data['totals'][k]:.2f}".replace(".", ",") for k in AMOUNTS])
        for warning in self.data["warnings"]:
            writer.writerow(["VERIFICARE", safe(warning)])
        name = f"Jurnal_{self.kind}_{self.date_from}_{self.date_to}.csv"
        super(Journal, self).write({"export_file": base64.b64encode(output.getvalue().encode("utf-8-sig")),
                                   "export_name": name})
        return {"type": "ir.actions.act_url", "url":
                f"/web/content/gt.ro.vat.journal/{self.id}/export_file/{name}?download=true", "target": "download"}

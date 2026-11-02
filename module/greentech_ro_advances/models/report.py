import base64
import csv
from collections import defaultdict
from io import StringIO, BytesIO
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from markupsafe import Markup, escape
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class Report(models.TransientModel):
    _name = "gt.advance.report"
    _description = "Situația avansurilor"

    company_id = fields.Many2one("res.company", "Firmă", required=True, default=lambda s: s.env.company)
    kind = fields.Selection([("sale", "Avansuri clienți"), ("purchase", "Avansuri furnizori")],
                            default="sale", required=True, string="Situație")
    date_from = fields.Date("De la", required=True, default=lambda s: fields.Date.today().replace(day=1))
    date_to = fields.Date("Până la", required=True, default=fields.Date.context_today)
    partner_id = fields.Many2one("res.partner", "Partener")
    hide_zero = fields.Boolean("Ascunde soldurile finale zero")
    data = fields.Json(readonly=True)
    display_html = fields.Html("Rezultatul situației", readonly=True)
    export_file = fields.Binary(attachment=False, readonly=True)
    export_name = fields.Char(readonly=True)
    _outputs = {"data", "display_html", "export_file", "export_name"}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self._outputs.intersection(vals):
                raise AccessError("Situația se calculează din contabilitate.")
            vals.update({f: False for f in self._outputs})
        return super().create(vals_list)

    def write(self, vals):
        if self._outputs.intersection(vals):
            raise AccessError("Situația se calculează din contabilitate.")
        if {"company_id", "kind", "date_from", "date_to", "partner_id", "hide_zero"}.intersection(vals):
            vals = dict(vals, **{f: False for f in self._outputs})
        return super().write(vals)

    def _domain(self):
        self.ensure_one()
        self.check_access("read")
        if self.company_id not in self.env.companies:
            raise AccessError("Firma nu este autorizată.")
        if self.date_from > self.date_to:
            raise UserError("Intervalul este invalid.")
        domain = [("company_id", "=", self.company_id.id), ("parent_state", "=", "posted"),
                  ("account_id.code", "=like", ("419" if self.kind == "sale" else "409") + "%"),
                  ("date", "<=", self.date_to)]
        if self.partner_id:
            domain.append(("partner_id.commercial_partner_id", "=", self.partner_id.commercial_partner_id.id))
        return domain

    def action_refresh(self):
        lines = self.env["account.move.line"].with_company(self.company_id).search(self._domain(), order="date,move_id,id")
        groups = defaultdict(lambda: {"opening": 0, "debit": 0, "credit": 0, "closing": 0})
        details = []
        sign = -1 if self.kind == "sale" else 1
        for line in lines:
            partner = line.partner_id.commercial_partner_id
            key = (partner.id, line.account_id.id)
            row = groups[key]
            row.update(partner=partner.name or "Fără partener", partner_id=partner.id,
                       account=line.account_id.code)
            if line.date < self.date_from:
                row["opening"] += sign * line.balance
            else:
                row["debit"] += line.debit
                row["credit"] += line.credit
                details.append({
                    "date": str(line.date), "document": line.move_id.name,
                    "reference": line.move_id.ref or "", "partner": row["partner"],
                    "account": row["account"], "label": line.name or "",
                    "debit": line.debit, "credit": line.credit,
                    "currency": line.currency_id.name, "amount_currency": line.amount_currency,
                    "origin": line.gt_advance_origin_id.move_id.name or "",
                    "move_id": line.move_id.id,
                })
            row["closing"] += sign * line.balance
        rows = sorted(groups.values(), key=lambda r: (r["partner"], r["account"]))
        if self.hide_zero:
            rows = [r for r in rows if not self.company_id.currency_id.is_zero(r["closing"])]
            keys = {(r["partner"], r["account"]) for r in rows}
            details = [d for d in details if (d["partner"], d["account"]) in keys]
        totals = {k: sum(r[k] for r in rows) for k in ("opening", "debit", "credit", "closing")}
        data = {"company": self.company_id.name, "title": dict(self._fields["kind"].selection)[self.kind],
                "date_from": str(self.date_from), "date_to": str(self.date_to),
                "currency": self.company_id.currency_id.name, "summary": rows, "details": details, "totals": totals}
        def table(headers, values):
            return Markup('<table class="table table-sm table-striped"><thead><tr>') + Markup("").join(
                Markup("<th>%s</th>") % escape(h) for h in headers) + Markup("</tr></thead><tbody>") + Markup("").join(
                Markup("<tr>") + Markup("").join(Markup("<td>%s</td>") % escape(
                    f"{v:,.2f}" if isinstance(v, float) else str(v)) for v in row) + Markup("</tr>")
                for row in values) + Markup("</tbody></table>")
        html = Markup("<h3>%s</h3><p>Contabilizat · %s · sold pozitiv = avans rămas</p>") % (
            escape(data["title"]), escape(data["currency"]))
        html += table(["Partener", "Cont", "Sold inițial", "Debit", "Credit", "Sold final"],
                      [[r["partner"], r["account"], *[float(r[k]) for k in totals]] for r in rows]
                      + [["TOTAL", "", *[float(totals[k]) for k in totals]]])
        html += Markup("<h4>Documentele perioadei</h4>")
        html += table(["Data", "Document", "Partener", "Cont", "Debit", "Credit", "Factură avans"],
                      [[r[k] for k in ("date", "document", "partner", "account", "debit", "credit", "origin")] for r in details])
        super().write({"data": data, "display_html": html, "export_file": False, "export_name": False})
        return True

    def action_documents(self):
        domain = self._domain() + [("date", ">=", self.date_from)]
        return {"type": "ir.actions.act_window", "name": "Mișcări avansuri",
                "res_model": "account.move.line", "view_mode": "list,form", "domain": domain}

    def _download(self, raw, extension):
        name = f"Avansuri_{self.kind}_{self.date_from}_{self.date_to}.{extension}"
        super().write({"export_file": base64.b64encode(raw), "export_name": name})
        return {"type": "ir.actions.act_url", "target": "download",
                "url": f"/web/content/gt.advance.report/{self.id}/export_file/{name}?download=true"}

    def action_csv(self):
        self.action_refresh()
        out = StringIO(newline="")
        writer = csv.writer(out, delimiter=";")
        def safe(v):
            if isinstance(v, float):
                return f"{v:.2f}"
            return "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
        def row(values):
            writer.writerow([safe(v) for v in values])
        row([self.data["title"], self.data["company"], self.data["currency"], self.date_from, self.date_to])
        row(["Partener", "Cont", "Sold inițial", "Debit", "Credit", "Sold final"])
        keys = ("opening", "debit", "credit", "closing")
        for r in self.data["summary"]:
            row([r["partner"], r["account"], *[float(r[k]) for k in keys]])
        row(["TOTAL", "", *[float(self.data["totals"][k]) for k in keys]])
        row([])
        row(["Data", "Document", "Referință", "Partener", "Cont", "Descriere", "Debit", "Credit",
             "Monedă", "Sumă în monedă", "Factură avans"])
        for r in self.data["details"]:
            row([r[k] for k in ("date", "document", "reference", "partner", "account", "label",
                               "debit", "credit", "currency", "amount_currency", "origin")])
        return self._download(out.getvalue().encode("utf-8-sig"), "csv")

    def action_pdf(self):
        self.action_refresh()
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
        import reportlab
        font = "GTAdvance"
        if font not in pdfmetrics.getRegisteredFontNames():
            candidates = [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                          Path(reportlab.__file__).parent / "fonts/Vera.ttf"]
            pdfmetrics.registerFont(TTFont(font, str(next(p for p in candidates if p.exists()))))
        style = ParagraphStyle("text", fontName=font, fontSize=8, leading=11)
        heading = ParagraphStyle("title", parent=style, fontSize=18, leading=24, spaceAfter=12)
        def p(text, s=style):
            return Paragraph(xml_escape(str(text)), s)
        def table(headers, rows, widths):
            t = Table([[p(h) for h in headers]] + [[p(f"{c:,.2f}" if isinstance(c, float) else c) for c in r]
                                                 for r in rows], colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6eff3")),
                ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#c9d4dc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            return t
        d = self.data
        story = [p(d["title"], heading), p(d["company"]),
                 p(f'{d["date_from"]} - {d["date_to"]} | Moneda contabilă: {d["currency"]}'),
                 p("Sold pozitiv = avans rămas. Numai documente contabilizate; date contabile."), Spacer(1, 16)]
        keys = ("opening", "debit", "credit", "closing")
        summary = [[r["partner"], r["account"], *[float(r[k]) for k in keys]] for r in d["summary"]]
        summary.append(["TOTAL", "", *[float(d["totals"][k]) for k in keys]])
        story.append(table(["Partener", "Cont", "Sold inițial", "Debit", "Credit", "Sold final"],
                           summary, [270, 65, 110, 110, 110, 110]))
        story += [Spacer(1, 18), p("Documentele perioadei", heading)]
        story.append(table(["Data", "Document / referință", "Partener", "Cont", "Debit", "Credit", "Factură avans"],
                           [[r["date"], r["document"] + "\n" + r["reference"], r["partner"], r["account"],
                             float(r["debit"]), float(r["credit"]), r["origin"]] for r in d["details"]],
                           [65, 150, 180, 55, 90, 90, 145]))
        out = BytesIO()
        def footer(canvas, doc):
            canvas.setFont(font, 8)
            canvas.drawString(32, 18, f"Avansuri | {d['date_from']} - {d['date_to']}")
            canvas.drawRightString(810, 18, f"Pagina {doc.page}")
        SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=32, rightMargin=32,
                          topMargin=30, bottomMargin=32).build(story, onFirstPage=footer, onLaterPages=footer)
        return self._download(out.getvalue(), "pdf")

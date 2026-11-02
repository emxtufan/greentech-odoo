"""Local, embedded-font PDF exports. No browser, wkhtmltopdf or remote assets."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether


def render_pdf(data, vat, generated_at, partner="", deduction="all"):
    for name, candidates in [
        ("GTVat", [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                   Path(reportlab.__file__).parent / "fonts/Vera.ttf"]),
        ("GTVatBold", [Path("C:/Windows/Fonts/arialbd.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                       Path(reportlab.__file__).parent / "fonts/VeraBd.ttf"]),
    ]:
        if name not in pdfmetrics.getRegisteredFontNames():
            font = next(p for p in candidates if p.is_file())
            pdfmetrics.registerFont(TTFont(name, str(font)))
    pdfmetrics.registerFontFamily("GTVat", normal="GTVat", bold="GTVatBold")
    style = ParagraphStyle("text", fontName="GTVat", fontSize=8, leading=11, textColor=colors.HexColor("#183343"))
    heading = ParagraphStyle("heading", parent=style, fontName="GTVatBold", fontSize=12, leading=16, spaceBefore=13, spaceAfter=6)
    title_style = ParagraphStyle("title", parent=heading, fontSize=21, leading=25)
    small = ParagraphStyle("small", parent=style, fontSize=7, leading=9)
    right = ParagraphStyle("right", parent=small, alignment=TA_RIGHT)
    title = "Jurnal cumpărări" if data["kind"] == "purchase" else "Jurnal vânzări"
    def p(text, s=style):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), s)
    def money(value):
        return p(f"{value:,.2f}".translate(str.maketrans(",.", ".,")), right)
    width = landscape(A4)[0] - 24 * mm
    def table(headers, rows, widths):
        t = Table([[p(h, small) for h in headers]] + rows,
                  colWidths=[width * w for w in widths], repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eff3")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
            ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#ccd8df")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t
    story = [p(title, title_style), p(data["company"] + " · CUI " + (vat or "-")),
             p(f"Perioadă: {data['date_from']} - {data['date_to']} · Moneda: RON · Data contabilă"),
             p("Numai documente contabilizate. Generat: " + generated_at + " UTC", small)]
    if partner:
        story.append(p("Partener: " + partner))
    if deduction != "all":
        story.append(p(f"Filtru: TVA nedeductibilă {deduction}%"))
    if data["warnings"]:
        story.append(p(f"RAPORT CU OBSERVAȚII: {len(data['warnings'])} verificări necesare. Detalii la final.", heading))
    keys = ["base", "vat", "total", "eligible", "nondeductible", "pending_vat"]
    summaries = [[p(r["category"], small)] + [money(r[k]) for k in keys] for r in data["summary"]]
    summaries.append([p("TOTAL", small)] + [money(data["totals"][k]) for k in keys])
    story += [p("1. Totaluri pe categorii", heading), table(
        ["Categorie", "Bază document", "TVA document", "Total cu TVA", "TVA deductibilă / colectată",
         "TVA nedeductibilă", "TVA neexigibilă final"], summaries, [.28, .12, .12, .12, .12, .12, .12])]
    detail = [[p(r["date"], small), p(r["document"], small),
               p(r["partner"] + "\n" + r["vat_number"], small), p(r["category"], small)]
              + [money(r[k]) for k in ["base", "vat", "eligible", "nondeductible"]] for r in data["rows"]]
    story += [p("2. Documente", heading), table(
        ["Data", "Document", "Partener / CUI", "Categorie", "Bază", "TVA", "TVA deductibilă / colectată", "TVA nedeductibilă"],
        detail, [.08, .12, .19, .19, .105, .105, .105, .105])]
    cash = [r for r in data["rows"] if r["cash_basis"]]
    if cash:
        story += [p("3. TVA la plată / încasare: sume achitate în perioadă și sold final", heading),
                  table(["Document / categorie", "Achitat", "Bază achitată", "TVA achitată brut", "Neachitat",
                         "Bază neexigibilă", "TVA neexigibilă"],
                        [[p(r["document"] + "\n" + r["category"], small)]
                         + [money(r[k]) for k in ["paid", "paid_base", "paid_vat", "unpaid", "pending_base", "pending_vat"]]
                         for r in cash], [.28, .12, .12, .12, .12, .12, .12])]
        seen, settlements = set(), []
        for row in cash:
            for pay in row["payments"]:
                key = (row["move_id"], pay["partial_id"])
                if key not in seen:
                    seen.add(key)
                    settlements.append([p(row["document"], small), p(pay["date"], small), p(pay["document"], small),
                                        p(pay["kind"], small), money(pay["amount"]),
                                        p("În perioadă" if pay["in_period"] else "Anterior", small)])
        if settlements:
            story += [p("Documente de decontare (sume pe document, fără dublare pe cote TVA)", heading),
                      table(["Factură", "Data", "Document decontare", "Tip", "Sumă RON", "Perioadă"], settlements,
                            [.24, .1, .24, .18, .12, .12])]
    story += [Spacer(1, 8), p(
        "TVA exigibilă este preluată din contabilitate. La taxare inversă, totalul fiscal bază + TVA poate diferi de suma datorată furnizorului. "
        "La valută, baza achitată și soldul sunt evaluate la cursul facturii; TVA exigibilă provine din notele contabile la plată.", small)]
    if data["warnings"]:
        story.append(p("Observații și verificări", heading))
        story += [p("• " + w, small) for w in data["warnings"]]
    story.append(p(f"Note excluse explicit: {data['excluded_notes']}. Raportul nu reprezintă o declarație depusă la ANAF.", small))
    out = BytesIO()
    document = SimpleDocTemplate(out, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm,
                                 topMargin=12*mm, bottomMargin=15*mm, title=title, author=data["company"])
    def footer(canvas, doc):
        canvas.setFont("GTVat", 7)
        canvas.setFillColor(colors.HexColor("#657581"))
        canvas.drawString(12*mm, 8*mm, title + " · " + data["date_from"] + " - " + data["date_to"])
        canvas.drawRightString(landscape(A4)[0] - 12*mm, 8*mm, f"Pagina {doc.page}")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()

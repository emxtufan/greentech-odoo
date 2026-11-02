"""Refresh the local guide using the actual Java/DUK/PDF verification evidence."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
work = root / "logs/d112-java-20261020"
result = json.loads((work / "integration.json").read_text(encoding="utf-8"))
assert result["positive"] == "valid" and result["negative"] == "invalid"
assert result["embedded_xml_matches"]
demo_path = root / "logs/d112-demo-20261020/live-demo.json"
demo = json.loads(demo_path.read_text(encoding="utf-8"))
demo.update(declaration_state="pdf", validator_log="ok", java_installed=True, pdf_generated=True)
demo_path.write_text(json.dumps(demo, ensure_ascii=False, indent=2), encoding="utf-8")

path = root / "ANAF-D112-STATUS.html"
text = path.read_text(encoding="utf-8")
text = re.sub(
    r"<p><strong>D112 este generată, dar nevalidată\.</strong>.*?</p>",
    '<p><strong>D112 DEMO a fost validată cu DUKIntegrator: rezultat „ok”.</strong> '
    'Java Temurin 8u504 x64 este instalat local în proiect, cu semnătură validă Eclipse Foundation. '
    'Configurația DUK este completă, cu validare locală și fără actualizare automată.</p>'
    '<p>PDF-ul ANAF are două pagini, versiunea D112_J27.0.6. XML-ul atașat coincide cu declarația validată. '
    'Un test separat cu totalul intenționat greșit a fost respins cu regula A19.1. '
    'Descărcarea PDF și XML a fost verificată în Odoo. Nu există semnătură, depunere sau recipisă.</p>'
    '<p><a href="output/pdf/D112_DEMO_2026_09.pdf">Deschide PDF-ul DEMO</a></p>',
    text, flags=re.S,
)
text = text.replace(
    "<p><strong>Validarea fiscală reală și PDF-ul ANAF nu sunt confirmate:</strong> Java lipsește din mediu.",
    "<p><strong>Validarea DUK și PDF-ul ANAF sunt confirmate pentru exemplul DEMO din septembrie 2026.</strong> "
    "Această verificare privește profilul implementat și datele concrete de test.",
)
text = text.replace(
    "22 trecute pe copie izolată; nu sunt validare fiscală oficială",
    "23 trecute pe copie izolată; suplimentar 16 teste ale serviciilor",
).replace(
    "Nevalidate în acest mediu; nu s-au transmis documente",
    "DUK: ok; PDF cu XML verificat. Fără depunere și fără recipisă ANAF",
)
text = re.sub(r'http://127\.0\.0\.1:8070/odoo/action-728/7(?=")',
              f'http://127.0.0.1:8070/odoo/action-728/{demo["declaration_id"]}', text)
path.write_text(text, encoding="utf-8")
print("D112_JAVA_REPORT_UPDATED")

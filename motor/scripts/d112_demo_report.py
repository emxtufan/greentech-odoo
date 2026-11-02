"""Add the verified fictitious company example to the local guide."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
work = root / "logs/d112-demo-20261020"
demo = json.loads((work / "live-demo.json").read_text(encoding="utf-8"))
assert json.loads((work / "browser-live.json").read_text())["status"] == "passed"
assert demo["other_company_hr_unchanged"] and demo["fictitious_only"] and not demo["submitted"]
guide = root / "ANAF-D112-STATUS.html"
text = guide.read_text(encoding="utf-8")
text = re.sub(r"<!-- DEMO-START -->.*?<!-- DEMO-END -->\n?", "", text, flags=re.S)
section = f"""<!-- DEMO-START -->
<section class="card"><h2>Exemplu pregătit: GreenTech Financiar DEMO - date fictive</h2>
<p><strong>Septembrie 2026:</strong> trei salariați fictivi, fiecare cu 22 zile lucrate.
Identificatorii și pontajul sunt sintetici, exclusiv pentru testarea aplicației.</p>
<table><tr><th>Salariat DEMO</th><th>Brut</th><th>Net</th></tr>
<tr><td>Ion Popescu</td><td>11.000 lei</td><td>6.435 lei</td></tr>
<tr><td>Mara Ionescu</td><td>13.200 lei</td><td>7.732 lei</td></tr>
<tr><td>Radu Dumitrescu</td><td>8.800 lei</td><td>5.148 lei</td></tr>
<tr><th>Total</th><th>33.000 lei</th><th>19.315 lei</th></tr></table>
<p>CAS: 8.250 lei · CASS: 3.300 lei · Impozit: 2.135 lei · CAM: 743 lei.
Fișa tehnică „Administrator” este exclusă explicit, deoarece nu are contract și salariu.
Această excludere este refuzată dacă există salariu sau un contract aplicabil.</p>
<p><a class="open" href="http://127.0.0.1:8070/odoo/action-730/{demo['period_id']}">Deschide statul DEMO</a>
<a href="http://127.0.0.1:8070/odoo/action-728/{demo['declaration_id']}">Deschide D112 DEMO</a></p>
<p><strong>D112 este generată, dar nevalidată.</strong> Descărcarea Java a fost blocată de restricția de rețea
a mediului (WinError 10013); Java nu a fost instalat. Pentru continuare este necesară o arhivă locală
<a href="https://adoptium.net/temurin/releases/?version=8&amp;os=windows&amp;arch=x64&amp;package=jre">Temurin 8, Windows x64, JRE, ZIP</a>.
Datele fictive nu sunt destinate semnării sau depunerii.</p>
<p>Verificare: 23 teste Odoo fără erori pe copia bazei; statul, cele trei rânduri salariale și descărcarea XML
verificate în browser pe copie și pe instanța locală. Documentele contabile și datele HR ale celeilalte firme
au rămas neschimbate. Backup înaintea actualizării:
<code>logs/backups/greentech-financiar-test-20261020-115756.zip</code>.</p>
<img alt="Stat salarial fictiv pentru septembrie 2026" src="logs/d112-demo-20261020/live-demo-payroll.png">
</section><!-- DEMO-END -->
"""
anchor = '<section class="card notice">'
assert anchor in text
guide.write_text(text.replace(anchor, section + anchor, 1), encoding="utf-8")
print("D112_DEMO_GUIDE_UPDATED")
if (root / "logs/d112-java-20261020/integration.json").exists():
    import runpy
    runpy.run_path(str(root / "scripts/d112_java_report.py"))

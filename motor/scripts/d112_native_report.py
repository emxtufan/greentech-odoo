"""Publish the local native payroll guide after deployment and UI verification."""
from pathlib import Path
import html
import json

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "logs/d112-native-20261020"
browser = json.loads((WORK / "browser-live.json").read_text())
assert browser["status"] == "passed"
verified = json.loads((WORK / "live-verified.json").read_text())
state = json.loads((WORK / "state.json").read_text())
backup = html.escape(Path(state["backup"]).relative_to(ROOT).as_posix(), quote=True)
url = f"http://127.0.0.1:8070/odoo/action-{browser['action']}"
report = f"""<!doctype html><html lang="ro"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ANAF — Salarii și D112 din Odoo</title>
<style>
body{{font:16px/1.65 system-ui,sans-serif;background:#f2f5f7;color:#183343;margin:0}}
main{{max-width:1060px;margin:auto;padding:36px 24px}}h1{{font-size:36px;line-height:1.2}}
.card{{background:white;border:1px solid #dbe4e9;border-radius:12px;padding:24px;margin:20px 0}}
.notice{{border-left:5px solid #b87d14;background:#fff9e9}}
.open{{display:inline-block;background:#135779;color:white;padding:10px 22px;border-radius:6px;text-decoration:none}}
a{{color:#135779}}td,th{{padding:10px;border-bottom:1px solid #dbe4e9;text-align:left}}
table{{width:100%;border-collapse:collapse}}code{{font-size:12px;overflow-wrap:anywhere}}small{{color:#657581}}
img{{max-width:100%;border:1px solid #dbe4e9}}
</style><main>
<small>Odoo 19 local · 20 octombrie 2026</small>
<h1>ANAF → State salariale → D112</h1>
<p>Generarea pornește din angajații și contractele Odoo. Nu necesită SAGA sau un XML importat.</p>
<a class="open" href="{url}">Deschide State salariale</a>
<section class="card notice"><h2>Starea reală a implementării</h2>
<p>Calculul salarial și generarea XML funcționează pentru profilul de mai jos și au fost testate pe o copie separată.
Nu reprezintă încă un motor complet de salarizare pentru toate situațiile fiscale.</p>
<p><strong>Validarea fiscală reală și PDF-ul ANAF nu sunt confirmate:</strong> Java lipsește din mediu.
Nu s-a semnat sau transmis nicio declarație. Pentru prima declarație a firmei trebuie completate firma/perioada,
contractele, profilurile fiscale și pontajele reale.</p></section>
<section class="card"><h2>Utilizare</h2><ol>
<li>În <strong>Angajați</strong>, completează CNP, data nașterii, salariul, începutul contractului și programul de lucru.
În fila <strong>ANAF / salarizare</strong>, completează numele separat, casa de sănătate, funcția de bază,
persoanele în întreținere și copiii eligibili, pe baza documentelor.</li>
<li>În <strong>ANAF → State salariale → Nou(ă)</strong>, alege firma și luna; completează CAEN, casa de sănătate și semnatarul.
Confirmă profilul lunar la sediul principal numai dacă se aplică firmei.</li>
<li>Apasă <strong>Preia angajați și contracte</strong>. Completează zilele efectiv lucrate și eventualele prime.
Verifică fiecare fișă și bifează confirmarea pontajului/profilului. Nu se presupune automat că luna a fost lucrată integral.</li>
<li>Apasă <strong>Calculează salariile</strong>. Fila <strong>Verificări</strong> explică orice informație lipsă sau caz neimplementat.
La succes apar brutul, CAS, CASS, deducerile, impozitul, netul și CAM.</li>
<li>Apasă <strong>Generează D112</strong>. Angajatorul, asigurații, obligațiile și secțiunile salariale sunt construite din stat.
Declarația păstrează legătura și amprenta statului sursă.</li>
<li>În declarație, <strong>Validează ANAF</strong> execută DUKIntegrator după configurarea Java în <strong>ANAF → Configurare</strong>.
Numai rezultatul explicit al validatorului poate acorda starea „Validat DUKIntegrator”.</li>
<li>În <strong>Fișiere</strong>, XML-ul de lucru este etichetat <strong>NEVALIDAT</strong>.
PDF-ul ANAF devine disponibil numai după validare. Semnarea/depunerea și recipisa se tratează separat.</li>
</ol></section>
<section class="card"><h2>Profilul disponibil: 07–10/2026</h2>
<p>CIM cu normă întreagă, 8 ore/zi, 40 ore/săptămână, program luni–vineri,
salariat rezident major, nepensionar, condiții normale și lună integral lucrată.
Salariu și prime în lei întregi; deduceri personale art.77; facilitatea de 200 lei când condițiile OUG 89/2025 sunt îndeplinite.
CAM se rotunjește la baza totală a angajatorului.</p>
<p><strong>Nu sunt implementate:</strong> CO/CM și alte concedii, suspendări, timp parțial,
angajări/încetări/modificări de contract în cursul lunii, pensionari, tichete, diurne, ore suplimentare,
scutiri, alte deduceri, condiții speciale, venituri nesalariale, sedii secundare, raportare trimestrială
și rectificarea unui stat cu declarație depusă. Aceste situații nu trebuie încadrate artificial în profilul normal.</p>
<p>Modulul nu creează note contabile sau plăți. Statul demonstrativ anterior rămâne separat.</p></section>
<section class="card notice"><h2>XSD-ul furnizat de tine</h2>
<p>Fișierul <code>d112_0726_140826 (1).xsd</code> a fost integrat fără modificări.
SHA256: <code>9603d3aa1b0bd7b56f91584e41ecdc3a09dda3abf724631f42f27c24b9b45788</code>.</p>
<p>Originalul limitează câmpurile salariale <code>A_sal1/A_sal2</code> la 30 și tipul <code>A_1</code> la 30.
<a href="https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/structura_D112_0726_070926.pdf">Anexa oficială ANAF</a>
descrie salariile ca N(15) și include tipul 51. Aplicația păstrează sumele reale și afișează erorile XSD.
Pentru aceste trei neconcordanțe documentate, permite verificarea independentă DUK; raportul strict XSD nu este ascuns.
Alte erori de structură blochează în continuare validarea.</p></section>
<section class="card"><h2>Corecții și trasabilitate</h2>
<p>Folosește <strong>Redeschide pentru corecții</strong>, completează datele, reconfirmă pontajele și recalculează.
Declarațiile vechi sunt marcate ca provenind dintr-un stat redeschis și nu mai pot fi validate.
Schimbarea datelor angajatului sau contractului după calcul este detectată înaintea generării/validării.</p>
<p>Accesul este acordat prin grupul <strong>ANAF — Salarizare România</strong> și limitat la firmele autorizate.</p></section>
<section class="card"><h2>Verificări efectuate</h2>
<table><tr><th>Verificare</th><th>Rezultat</th></tr>
<tr><td>Teste Odoo, inclusiv calcul și D112 nativă</td><td>22 trecute pe copie izolată; nu sunt validare fiscală oficială</td></tr>
<tr><td>Interfață completă</td><td>Creare stat, date lipsă, pontaj, calcul, generare D112, erori XSD și Java, descărcare XML de lucru</td></tr>
<tr><td>Exemplu software, brut 8.000 lei</td><td>CAS 2.000; CASS 800; impozit 520; net 4.680; CAM 180</td></tr>
<tr><td>Exemplu software, minim 4.325 lei cu facilitate și fără persoane în întreținere</td><td>CAS 1.031; CASS 413; deducere 865; impozit 182; net 2.699</td></tr>
<tr><td>Date contabile existente</td><td>Amprente neschimbate: {verified['moves']['rows']} documente,
{verified['lines']['rows']} linii și {verified['payments']['rows']} plăți</td></tr>
<tr><td>DUK real / PDF / recipisă ANAF</td><td>Nevalidate în acest mediu; nu s-au transmis documente</td></tr></table>
<p><a href="logs/d112-native-20261020/browser-test.json">Test browser</a> ·
<a href="logs/d112-native-20261020/browser-live.json">Verificare instanță activă</a> ·
<a href="logs/d112-native-20261020/live-verified.json">Integritate contabilă</a> ·
<a href="{backup}">Backup înaintea instalării</a></p>
<img src="logs/d112-native-20261020/native-calculated.png" alt="Exemplu software pe baza separată de test"></section>
<section class="card"><h2>Surse</h2>
<p><a href="https://static.anaf.ro/static/10/Anaf/Declaratii_R/112.html">ANAF D112</a> ·
<a href="https://legislatie.just.ro/Public/DetaliiDocument/308231">HG 146/2026</a> ·
<a href="https://legislatie.just.ro/Public/DetaliiDocument/305817">OUG 89/2025</a> ·
<a href="https://legislatie.just.ro/Public/DetaliiDocument/262588">Tabel deduceri art.77</a>.</p>
<p>Instalare locală, port 8070. Serverul Linux nu a fost modificat.
Module: <code>greentech_ro_payroll</code> și <code>greentech_anaf_d112</code>.</p></section>
</main></html>"""
(ROOT / "ANAF-D112-STATUS.html").write_text(report, encoding="utf-8")
print("NATIVE_D112_GUIDE_READY", url)
if (ROOT / "logs/d112-demo-20261020/live-demo.json").exists():
    import runpy
    runpy.run_path(str(ROOT / "scripts/d112_demo_report.py"))

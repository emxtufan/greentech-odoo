"""Build a local research report from the source and database snapshots.

Does not connect to Odoo, install addons, modify accounting data or contact ANAF.
"""
import ast
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "logs/ro-localization-review-20261020"


def main():
    source = json.loads((REVIEW / "sources.json").read_text(encoding="utf-8"))
    matrix = json.loads((REVIEW / "module-matrix.json").read_text(encoding="utf-8"))
    installed = json.loads((REVIEW / "installed-modules.json").read_text(encoding="utf-8"))
    assert len(matrix) == 44
    assert source["oca_commit"] == "8aec9cebe5d6fba7cdcc0f8d9216dee97ca9f5dc"
    for file in source["manifests"]:
        raw = file["content"].encode("utf-8")
        digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        assert digest == file["sha"] == file["tree_sha"], file["path"]
        assert ast.literal_eval(file["content"])["version"].startswith("19.0.")
    assert not any("d112" in item["module"].lower() for item in matrix)
    assert sum(item["state"] == "installed" for item in matrix) == 3
    assert installed["l10n_ro_edi"]["state"] == "installed"

    rows = []
    for item in matrix:
        name = html.escape(item["module"])
        deps = ", ".join(item["depends"])
        status = "Instalat" if item["state"] == "installed" else "Neinstalat"
        url = f'https://github.com/OCA/l10n-romania/blob/{source["oca_commit"]}/{name}/__manifest__.py'
        rows.append(
            f'<tr><td><a href="{url}"><code>{name}</code></a></td>'
            f'<td>{html.escape(item["version"])}</td><td>{status}</td>'
            f'<td>{html.escape(deps)}</td></tr>'
        )

    document = """<!doctype html>
<html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GreenTech - Analiza contabilității România / Odoo 19</title>
<style>
:root{font-family:Segoe UI,Arial,sans-serif;color:#17312e;background:#f3f6f4}
body{margin:0 auto;max-width:1120px;padding:38px 24px 70px;line-height:1.65}
header{border-bottom:3px solid #16765b;padding-bottom:22px}
h1{font-size:32px;line-height:1.2;margin:8px 0 16px}
h2{font-size:23px;margin-top:34px} h3{font-size:18px}
a{color:#09624d} p{max-width:1000px}
.meta{font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:#536b64}
.note{padding:16px 20px;background:#fff8e7;border-left:4px solid #b58424;margin:22px 0}
.ok{background:#e5f1ea;border-left-color:#16765b}
table{border-collapse:collapse;width:100%;background:white;margin:16px 0;font-size:14px}
th,td{text-align:left;vertical-align:top;padding:11px 13px;border:1px solid #d5dfda}
th{background:#e7eeea} code{font-size:.9em;overflow-wrap:anywhere}
.table-wrap{overflow-x:auto}.small{font-size:13px;color:#50625b}
li{margin:7px 0} footer{margin-top:36px;border-top:1px solid #bccfc4;padding-top:16px}
@media print{body{max-width:none;padding:0;background:white;font-size:10pt}
 h1{font-size:24pt}h2{break-after:avoid} tr{break-inside:avoid}
 .table-wrap{overflow:visible}th,td{padding:6px}a{color:inherit}header{break-inside:avoid}}
</style></head><body>
<header><div class="meta">GreenTech · analiză tehnică · 20 octombrie 2026</div>
<h1>Contabilitate românească în Odoo 19</h1>
<p>Evaluarea surselor indicate, a modulului D112 și a compatibilității cu
instalația Community existentă. Verificarea bazei a fost exclusiv în mod citire.</p></header>

<div class="note"><strong>Concluzia pentru implementare:</strong>
modulul din adresa Odoo Apps pentru 18.0 nu a putut fi verificat.
Wiki-ul documentează un modul distinct, <code>l10n_ro_anaf_d112</code>, pentru 19.0,
dar codul indicat nu este accesibil prin conector. Dependențele documentate
includ componente Enterprise inexistente în proiect.
<strong>D112 nu a fost instalat și nu s-a generat o declarație fiscală.</strong></div>

<h2>1. Ce ne oferă fiecare sursă</h2>
<div class="table-wrap"><table>
<thead><tr><th>Sursa</th><th>Ce am verificat</th><th>Consecința pentru proiect</th></tr></thead><tbody>
<tr><td><a href="https://apps.odoo.com/apps/modules/18.0/l10n_ro_d112">Odoo Apps: l10n_ro_d112 / 18.0</a></td>
<td>Pagina nu a putut fi recuperată; căutările nu au furnizat o fișă verificabilă
pentru acest nume exact.</td><td>Nu sunt confirmate autorul, prețul, licența,
dependențele sau existența unei ediții 19.0. Nu presupunem că este același modul
cu cel descris în wiki. Este necesară arhiva sursă sau o pagină accesibilă a furnizorului.</td></tr>
<tr><td><a href="https://github.com/dhongu/wiki_module_odoo/tree/19.0">Wiki Dorin Hongu / 19.0</a></td>
<td>README, catalog și fișele pentru D112, baza ANAF, puntea salarială,
DUK, pachetul de salarizare și pachetul contabil.</td><td>Documentație utilă pentru
funcții și dependențe. README precizează că este un wiki întreținut cu LLM;
nu reprezintă codul instalabil și nici dovada testării în mediul nostru.
Afirmațiile fiscale din fișe nu au fost auditate integral.</td></tr>
<tr><td><a href="https://github.com/odoo-romania/l10n-romania/blob/sync_branch/.github/workflows/main.yml">odoo-romania / sync_branch / workflow</a></td>
<td>Workflow de sincronizare Git, pornit la push, care folosește
<code>wei/git-sync@v3</code> pentru a copia ramurile OCA în oglinda odoo-romania.</td>
<td>Nu este modul contabil și nu furnizează D112. Pentru versiunea efectivă folosim
sursele OCA și un commit fixat, nu ramura de automatizare.</td></tr>
<tr><td>Ghid-Implementare-Odoo-RO.pdf<br>Aerya IT Solutions, ediția 2026, 52 pagini</td>
<td>Textul documentului și verificare vizuală a paginilor PDF 18–21;
capitolele contabilitate, localizare, HR și implementare.</td><td>Ghid de proces:
localizare, reconciliere, rapoarte, migrare și testare.
Nu livrează un generator D112. Pentru declarațiile salariale descrie folosirea
unui furnizor/contabil extern. Disponibilitatea modulelor trebuie verificată pe versiune.</td></tr>
<tr><td><a href="https://github.com/OCA/l10n-romania/tree/19.0">OCA / l10n-romania / 19.0</a></td>
<td>Arborele complet și manifestele tuturor celor 44 de module;
versiuni, licențe, dependențe și comparație cu baza locală.
Conținutul manifestelor a fost verificat față de hash-ul Git.</td>
<td>44 module marcate instalabile, cu licență AGPL-3.
Trei sunt deja instalate. D112 nu apare în acest arbore.
Fragmentul <code>#13.0</code> din linkul inițial nu selectează ramura 13.0.</td></tr>
</tbody></table></div>

<h2>2. D112: lanțul de dependențe și blocajul real</h2>
<p>Fișa publică descrie <code>l10n_ro_anaf_d112</code>, versiunea
<code>19.0.2.15.0</code>, cu evidență nominală, export XML și reconciliere.
Sursa indicată este
<a href="https://github.com/terrabit-solutions/l10n_ro_ent/tree/19.0/l10n_ro_anaf_d112">terrabit-solutions/l10n_ro_ent</a>.
Cererea pentru manifest a returnat 404. Aceasta indică lipsa accesului prin
conexiunea curentă; nu demonstrează inexistența depozitului.</p>
<pre><code>l10n_ro_anaf_d112
 ├─ account, hr, l10n_ro
 ├─ l10n_ro_reports
 └─ l10n_ro_anaf_base
     ├─ account_reports
     ├─ accountant
     └─ l10n_ro

l10n_ro_anaf_d112_payroll
 ├─ l10n_ro_anaf_d112
 └─ hr_payroll</code></pre>
<p>Acest lanț este extras din
<a href="https://github.com/dhongu/wiki_module_odoo/blob/19.0/l10n_ro_anaf_d112/index.md">fișa D112</a>,
<a href="https://github.com/dhongu/wiki_module_odoo/blob/19.0/l10n_ro_anaf_base/index.md">fișa bazei ANAF</a>
și <a href="https://github.com/dhongu/wiki_module_odoo/blob/19.0/l10n_ro_anaf_d112_payroll/index.md">fișa punții salariale</a>.
Manifestele reale ale acestor module nu au fost disponibile pentru confirmare.</p>
<p>Chiar dacă D112 poate primi valori manual fără <code>hr_payroll</code>,
dependența contabilă Enterprise rămâne. În baza locală,
<code>account_reports</code>, <code>l10n_ro_reports</code>,
<code>hr_payroll</code> și <code>l10n_ro_hr_payroll</code> nu sunt prezente;
<code>accountant</code> este marcat <code>uninstallable</code>.
Modulul nostru <code>greentech_hr_payroll_demo</code> folosește
<code>gt.payroll.slip</code>, iar puntea documentată citește
<code>hr.payslip</code>; nu există compatibilitate automată între ele.</p>

<h2>3. Ce este deja disponibil local</h2>
<ul>
<li>Odoo 19 Community, PostgreSQL 18.1; baza financiară are 92 module instalate.</li>
<li>Localizare: <code>l10n_ro</code>, <code>l10n_ro_config</code>,
<code>l10n_ro_account</code>, <code>l10n_ro_account_period_close</code>.</li>
<li>e-Factura: <code>l10n_ro_edi</code> este deja instalat.
Instalarea modulului nu confirmă autorizarea SPV sau transmiterea unei facturi.</li>
<li>Rapoarte și reconciliere: <code>account_financial_report</code>,
<code>account_reconcile_oca</code>, MIS, bugete, imobilizări și extensiile GreenTech.</li>
<li>SAGA: importul existent include documente reale. Istoricul salarial importat
nu conține detaliile individuale necesare pentru a reconstrui automat o D112.</li>
<li>Salarizarea GreenTech rămâne DEMO: nu constituie un motor salarial complet
și nu generează XML D112.</li>
</ul>

<h2>4. Ordinea propusă pentru extinderea Community</h2>
<p>Lista de mai jos este o selecție tehnică de candidați, nu o instalare efectuată.
Fiecare modul va necesita probă funcțională în copia izolată a bazei.</p>
<div class="table-wrap"><table><thead><tr><th>Grup</th><th>Module / utilitate</th><th>Condiții concrete</th></tr></thead><tbody>
<tr><td>Adrese și parteneri</td><td><code>l10n_ro_city</code>,
<code>l10n_ro_partner_create_by_vat</code>, <code>l10n_ro_partner_unique</code></td>
<td>SIRUTA/adrese, completare după CUI și controlul duplicatelor.
City cere <code>base_address_extended</code>. Se verifică partenerii existenți
înaintea introducerii restricțiilor de unicitate și serviciile ANAF separat.</td></tr>
<tr><td>Bancă</td><td><code>l10n_ro_account_bank_statement_report</code>;
importurile MT940 BRD/BCR/ING/Raiffeisen/Alpha/Exim</td><td>Raportul lucrează pe
extrasele Odoo, deci nu reconstituie automat extrasele istorice din notele SAGA.
Importul MT940 cere <code>account_statement_import_file</code>, care lipsește.
Primul import se validează cu un extras real și se verifică repetarea fără dubluri.</td></tr>
<tr><td>Casă și chitanțe</td><td><code>l10n_ro_payment_to_statement</code>,
<code>l10n_ro_payment_receipt_report</code></td><td>Modifică fluxul plăților și
numerotarea. Plățile de casă configurate creează poziții de registru și folosesc
reconcilierea cu contul metodei de plată. Trebuie armonizate cu jurnalele SAGA;
nu se activează direct peste istoricul contabil.</td></tr>
<tr><td>SPV</td><td><code>l10n_ro_message_spv</code></td><td>Extinde e-Factura cu
mesaje și prelucrarea documentelor primite. Cere și <code>account_edi</code>.
Include sarcini programate și poate crea facturi furnizor în ciornă.
Se probează separat identitatea companiei, accesul SPV și detectarea duplicatelor.</td></tr>
<tr><td>TVA</td><td><code>l10n_ro_vat_on_payment</code>,
<code>l10n_ro_fiscal_validation</code>, <code>l10n_ro_nondeductible_vat</code></td>
<td>Se aleg în funcție de regimurile reale ale companiilor.
TVA la încasare introduce verificări ANAF și poziții fiscale.
Modulul de TVA nedeductibil are și dependențe de contabilitate de stoc;
nu este doar un raport. Aceste module nu înlocuiesc generatorul D300/D394.</td></tr>
<tr><td>Documente și valută</td><td><code>l10n_ro_account_report_invoice</code>,
<code>l10n_ro_account_edit_currency_rate</code></td><td>Cer, respectiv,
<code>sale</code> și <code>sale_management</code>, absente în baza exclusiv financiară.
Se evaluează extinderea domeniului funcțional înainte de instalare.</td></tr>
<tr><td>Stocuri și importuri</td><td><code>l10n_ro_stock_account</code>,
<code>l10n_ro_stock_report</code>, <code>l10n_ro_stock_picking_valued_report</code>,
<code>l10n_ro_dvi</code></td><td>Etapă distinctă dacă se dorește gestiune.
Adaugă operațiuni și evaluare de stoc; instalarea tuturor modulelor OCA
ar modifica semnificativ aplicația financiară actuală.</td></tr>
</tbody></table></div>
<p class="small">Surse de comportament:
<a href="https://github.com/OCA/l10n-romania/tree/19.0/l10n_ro_account_bank_statement_report">raport bancă/casă</a>,
<a href="https://github.com/OCA/l10n-romania/tree/19.0/l10n_ro_payment_to_statement">plăți și registru de casă</a>,
<a href="https://github.com/OCA/l10n-romania/tree/19.0/l10n_ro_message_spv">mesaje SPV</a>,
<a href="https://github.com/OCA/l10n-romania/tree/19.0/l10n_ro_vat_on_payment">TVA la încasare</a>.
Dependențele din anexă provin din manifestele verificate.</p>

<h2>5. Ce trebuie corectat în interpretarea ghidului</h2>
<p>Ghidul este util ca metodă de implementare, dar lista de funcționalități nu
garantează că fiecare modul există pe ramura aleasă.
De exemplu, <code>l10n_ro_etransport</code>, menționat la paginile PDF 18–21,
nu este prezent în arborele OCA 19.0 verificat. Nu putem promite instalarea lui
din acest snapshot. Recomandările de rapoarte și reconciliere din ghid sunt
în mare parte deja acoperite de proiect.</p>

<h2>6. Implementarea D112: intrări și criterii de acceptare</h2>
<p>Pentru perioada octombrie 2026, pagina oficială ANAF indică formularul
aplicabil din luna 07/2026 și anexa de validări actualizată la 07.09.2026.
Sunt disponibile <a href="https://static.anaf.ro/static/10/Anaf/Declaratii_R/112.html">pagina D112</a>,
<a href="https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/structura_D112_0726_070926.pdf">structura și validările</a>
și <a href="https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/d112_0726_140826.xsd">schema XSD</a>.
Această verificare nu reprezintă un audit al tuturor regulilor fiscale.</p>
<ol>
<li><strong>Obținerea pachetului instalabil:</strong> arhiva modulului, manifestul,
licența și dependențele complete. Se confirmă explicit Odoo 19 Community sau
Enterprise. Un modul 18.0 necesită evaluare/migrare; schimbarea numărului din
manifest nu demonstrează compatibilitatea.</li>
<li><strong>Alegerea căii:</strong> rămânerea pe Community cu un generator și
un motor salarial compatibile, sau adoptarea unei soluții Enterprise cu licențele
necesare. Documentația disponibilă nu justifică trecerea automată la Enterprise.</li>
<li><strong>Izolarea:</strong> backup PostgreSQL și filestore, copie de test
cu transmisii externe și cron dezactivate. Modulele noi intră întâi în această copie.</li>
<li><strong>Maparea datelor:</strong> angajator, CNP și identitate nominală,
tipul contractului, zile, venituri, contribuții, deduceri și certificate medicale
dintr-o sursă salarială completă. Datele lipsă nu se deduc din totalurile contabile.</li>
<li><strong>Verificarea exportului:</strong> schemă oficială potrivită perioadei,
validări de structură și reguli DUK, reconciliere cu statele și contabilitatea.
Dacă furnizorul modifică local schema XSD, diferențele se documentează și
se verifică în validatorul oficial; un XSD relaxat nu demonstrează acceptarea ANAF.</li>
<li><strong>Cazuri de test:</strong> salariu standard, praguri salariale,
normă parțială, angajare/încetare, CO/CM, diurne/beneficii, rectificativă,
CNP invalid/duplicat, izolare între companii și regenerare fără dubluri.</li>
<li><strong>Activarea:</strong> numai după verificarea compatibilității,
a rezultatelor și a restaurării backupului. Instalarea pe serverul Linux
este un pas separat față de verificarea locală. Depunerea sau semnarea
declarațiilor nu este inclusă în analiza curentă.</li>
</ol>

<h2>7. Inventarul complet OCA 19.0</h2>
<p>Toate cele 44 de manifeste declară licența AGPL-3 și
<code>installable=True</code>. Aceste metadate nu înlocuiesc testarea
funcțională. Fiecare nume de modul trimite la manifestul din commitul verificat.</p>
<div class="table-wrap"><table><thead><tr><th>Modul</th><th>Versiune</th>
<th>Stare locală</th><th>Dependențe Odoo directe</th></tr></thead>
<tbody>__ROWS__</tbody></table></div>
<p>Dependențe Python declarate suplimentar:
<code>python-dateutil</code> pentru închidere și
<code>num2words&gt;=0.5.8</code> pentru chitanțe.</p>

<footer><p><strong>Trasabilitate:</strong> OCA <code>__OCA__</code>;
wiki <code>__WIKI__</code>. Manifestele și matricea sunt păstrate local în
<code>logs/ro-localization-review-20261020/</code>.</p>
<p><strong>Executat:</strong> cercetare web/GitHub, citire PDF,
verificarea manifestelor și interogarea bazei în mod read-only.
<strong>Neexecutat:</strong> instalarea D112, schimbarea ediției Odoo,
modificarea datelor contabile, actualizarea serverului și transmiterea către ANAF.</p>
</footer></body></html>"""
    document = document.replace("__ROWS__", "\n".join(rows))
    document = document.replace("__OCA__", source["oca_commit"])
    document = document.replace("__WIKI__", source["wiki_commit"])
    output = ROOT / "ANALIZA-CONTABILITATE-ROMANIA.html"
    output.write_text(document, encoding="utf-8")
    print(json.dumps({"output": str(output), "oca_modules": len(matrix),
                      "installed_oca_modules": 3, "d112_installed": False},
                     ensure_ascii=True))


if __name__ == "__main__":
    main()

"""Build the current local installation report from recorded verification."""
import ast
from html import escape
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "logs/oca-ro-install-20261020"


def read(name):
    return json.loads((WORK / name).read_text(encoding="utf-8"))


selection = read("selection.json")
verified = read("live-verified.json")
smoke = read("smoke.json")
http = read("http-verified.json")
assert http["status"] == smoke["status"] == "passed"
rows = []
for name in selection["modules"]:
    folder = "oca-ro-19" if name.startswith("l10n_ro_") else "bank-statement-import"
    source = selection["repositories"][0 if folder == "oca-ro-19" else 1]
    manifest = ast.literal_eval((ROOT / "third_party_addons" / folder / name / "__manifest__.py").read_text(encoding="utf-8"))
    url = f'https://github.com/{source["repo"]}/tree/{source["ref"]}/{name}'
    rows.append(
        f'<tr><td><a href="{url}">{escape(name)}</a><small>{escape(manifest["name"])}</small></td>'
        f'<td>{escape(verified["installed"][name])}</td><td>Instalat</td></tr>'
    )
new_count = len(verified["new_modules"])
sources = "".join(
    f'<li><a href="https://github.com/{s["repo"]}/tree/{s["ref"]}">{s["repo"]}</a>'
    f' — <code>{s["ref"]}</code></li>' for s in selection["repositories"]
)
html = f"""<!doctype html>
<html lang="ro"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Contabilitate România — instalare OCA</title>
<style>
body{{font:16px/1.6 system-ui,sans-serif;background:#f3f5f7;color:#172536;margin:0}}
main{{max-width:1080px;margin:auto;padding:40px 24px}}
h1{{font-size:34px;line-height:1.2}} h2{{margin-top:32px}}
.card{{background:white;padding:24px;border-radius:12px;margin:18px 0;border:1px solid #dbe3eb}}
.status{{display:inline-block;background:#d9f3e7;color:#17533c;padding:6px 14px;border-radius:20px}}
a{{color:#155a8e}}code{{font-size:12px;overflow-wrap:anywhere}}
table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;border-bottom:1px solid #dbe3eb;padding:10px}}
small{{display:block;color:#657081}}.muted{{color:#657081}}
@media(max-width:700px){{td,th{{font-size:12px;padding:6px}}main{{padding:18px 12px}}.card{{padding:14px}}}}
</style><main>
<p class="status">Instalare locală verificată • 20 octombrie 2026</p>
<h1>Contabilitate România: pachetul OCA instalat</h1>
<p>{new_count} module noi împreună cu dependențele lor; {len(verified["installed"])} module instalate în total.
Pachetul selectat cuprinde 30 de module din OCA/l10n-romania și 6 din OCA/bank-statement-import;
3 dintre cele 30 erau deja instalate.</p>
<div class="card"><h2>Deschidere</h2>
<p><a href="http://127.0.0.1:8070/odoo?db=greentech_financiar_test">Deschide instanța financiară locală</a>.
Lansatorul existent <code>10-DESCHIDE-FINANCIAR-DEMO.cmd</code> pornește serverul și copiază parola contului admin.
Baza conține și date contabile reale DARIUSMED importate din SAGA.</p>
<p>SPV: <strong>Financiar → Contabilitate → SPV → Mesaje SPV</strong>.
Importul extraselor este disponibil din jurnalul bancar. Configurarea fiscală se găsește în setările de contabilitate.</p></div>
<div class="card"><h2>Funcționalități instalate</h2>
<ul><li>e-Factura Odoo și mesajele SPV OCA; verificarea fiscală și completarea partenerilor după CUI.</li>
<li>Localități/SIRUTA, unicitatea partenerilor, TVA la încasare și TVA nedeductibilă.</li>
<li>Registru bancă/casă, plăți și chitanțe; import MT940 Alpha, BCR, BRD, EXIM, ING și Raiffeisen.</li>
<li>Import CAMT, CSV/TXT și XLSX, integrat cu reconcilierea OCA existentă.</li>
<li>Factură românească, curs valutar pe document, fișă de magazie, documente de stoc valorice, costuri suplimentare și DVI.</li>
<li>Rapoartele financiare, mijloacele fixe, bugetele și închiderea perioadelor deja instalate sunt păstrate.</li></ul></div>
<div class="card"><h2>Ce a fost verificat</h2>
<p>Instalare întâi pe o copie separată, apoi în <code>greentech_financiar_test</code>.
Amprentele SHA-256 ale câmpurilor contabile comparate sunt identice: {verified["moves"]["rows"]} înregistrări,
{verified["lines"]["rows"]} linii și {verified["payments"]["rows"]} plăți. Nu există note validate dezechilibrate.</p>
<p>{len(smoke["views"])} vizualizări încărcate prin ORM; factură HTML generată;
autentificare HTTP, {http["menus"]} meniuri, acces la SPV și {len(http["assets"])} pachete CSS/JS verificate.
Patru teste pentru citirea registrului ANAF pe Windows au trecut. Nu a fost efectuată inspecție vizuală în browser
sau validarea completă a fluxurilor fiscale.</p>
<p>Dovezi: <a href="logs/oca-ro-install-20261020/live-verified.json">integritate contabilă</a>,
<a href="logs/oca-ro-install-20261020/http-verified.json">HTTP/interfață</a>,
<a href="logs/oca-ro-install-20261020/smoke.json">formulare și factură</a>.</p></div>
<div class="card"><h2>Configurarea și verificările următoare</h2>
<p><strong>Nu există token ANAF/SPV configurat.</strong> Niciun document nu a fost transmis.
Sarcinile programate rămân inactive, cu <code>max_cron_threads=0</code>.</p>
<p>Registrul ANAF pentru TVA la încasare nu a fost descărcat. Lipsa sa păstrează statusul și data verificării nemodificate.
Trebuie verificate regimurile TVA, conturile pentru TVA nedeductibilă, configurarea jurnalelor de casă
și mapările extraselor. Modulul instalat nu impune automat regimul TVA al firmei.</p>
<p><strong>D112, D300, D394 și D406/SAF-T nu sunt generatoare incluse în sursele OCA 19 analizate.</strong>
Pregătirea D112 din modulul local de salarii rămâne demonstrativă.
Sursa D112 indicată în wiki depinde de module Enterprise/inaccesibile; modulul pentru Odoo 18 nu a fost portat.
Nu sunt instalate extensiile POS și gestiunea retail, care nu fac parte din fluxul solicitat.</p>
<p>Instalarea este locală. Serverul Linux nu a fost actualizat în această etapă.</p></div>
<div class="card"><h2>Surse, adaptări și backup</h2><ul>{sources}</ul>
<p>688 fișiere verificate după hash Git, păstrate în <code>third_party_addons/oca-ro-19</code> și
<code>third_party_addons/bank-statement-import</code>. Sunt incluse fișierele de execuție, licențele și traducerile românești;
testele upstream, exemplele și celelalte limbi nu au fost distribuite în acest pachet.</p>
<p>Adaptarea Windows înlocuiește <code>egrep</code> cu citire Python și elimină copierea automată a unei arhive de test ANAF.
Patch și amprente: <a href="logs/oca-ro-install-20261020/local-patches.patch">diferențe locale</a>,
<a href="logs/oca-ro-install-20261020/source-lock.json">surse fixate</a>.
La actualizarea OCA, reaplică și reverifică aceste adaptări.</p>
<p>Backup anterior instalării: <code>logs/oca-ro-install-20261020/before.dump</code> și
<code>logs/oca-ro-install-20261020/filestore-backup/</code>. Configurația anterioară este păstrată separat.
Restaurarea se face într-o bază nouă, împreună cu filestore-ul; revenirea doar la codul vechi nu restaurează schema bazei.</p></div>
<div class="card"><h2>Inventarul pachetului</h2>
<table><thead><tr><th>Modul și sursă</th><th>Versiune</th><th>Stare</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p class="muted">Analiza inițială a surselor, înaintea instalării: <a href="ANALIZA-CONTABILITATE-ROMANIA.html">raportul de analiză</a>.</p>
</main></html>"""
(ROOT / "STARE-INSTALARE-OCA-RO.html").write_text(html, encoding="utf-8")
print("OCA_INSTALL_REPORT_READY", len(rows), "modules")

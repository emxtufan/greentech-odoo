import html
import json
from datetime import datetime
from workflow_demo_client import Client, ROOT

c = Client()
s = c.state
verification = json.loads((ROOT / 'logs/workflow-verification.json').read_text(encoding='utf-8'))
db = c.credentials['database']
base = c.base

def url(model, record):
    return f'{base}/odoo/{model}/{record}?db={db}'

def anchor(label, model, record, css=''):
    return f'<a class="{css}" href="{url(model, record)}" target="_blank" rel="noopener">{html.escape(label)} ↗</a>'

native_action = c.call('project.project', 'action_view_tasks', [[s['project']]])
action_context = dict(native_action['context'])
action_context.pop('search_default_open_tasks', None)
dashboard = c.ensure('walkthrough_action', 'ir.actions.act_window', {
    'name': 'TEST - Flux complet GreenTech', 'path': 'flux-test', 'res_model': 'project.task',
    'view_mode': 'kanban,list,form,calendar,pivot,graph,activity',
    'domain': repr([('project_id', '=', s['project']), ('has_template_ancestor', '=', False)]),
    'context': repr(action_context)})
c.ensure('walkthrough_menu', 'ir.ui.menu', {'name': 'Flux complet TEST',
    'parent_id': c.ref('project.menu_main_pm'), 'sequence': 1,
    'action': f'ir.actions.act_window,{dashboard}'})
home = f'{base}/odoo/flux-test?db={db}'
c.credentials['url'] = home
(ROOT / 'config/acces-workflow-test.json').write_text(json.dumps(c.credentials, indent=2), encoding='utf-8')

records = {}
models = {'project': 'project.project', 'sale': 'sale.order', 'purchase': 'purchase.order',
          'receipt': 'stock.picking', 'delivery': 'stock.picking', 'customer_invoice': 'account.move',
          'vendor_bill': 'account.move', 'expense': 'hr.expense', 'bank_statement': 'account.bank.statement'}
for key, model in models.items():
    records[key] = c.read(model, s[key], ['display_name'])['display_name']

steps = [
    ('01', 'Proiect și buget', 'Proiecte → Flux complet TEST', 'project',
     'Lucrare fictivă de 5 kW: 10 panouri × 500 W. Proiectul are client, responsabil și cont analitic propriu.',
     '4 sarcini finalizate; fiecare document are legătură cu proiectul.',
     'Într-un flux nou: creezi proiectul, alegi clientul, responsabilul și contul analitic. Definești sarcinile de planificare, recepție, montaj și predare.'),
    ('02', 'Ofertă → comandă client', 'Vânzări → Comenzi', 'sale',
     '10 panouri × 600 lei + montaj la preț fix de 1.500 lei. Oferta a fost confirmată; Odoo a generat livrarea și sarcina de montaj.',
     '7.500 lei fără TVA · 1.575 lei TVA · 9.075 lei total.',
     'Creezi oferta, adaugi produsele și serviciul, verifici prețurile și taxele, apoi apeși Confirmă. În acest test nu s-au trimis emailuri clientului.'),
    ('03', 'Cerere de ofertă → achiziție', 'Achiziții → Comenzi', 'purchase',
     'Comandă către furnizorul fictiv pentru 10 panouri × 400 lei, legată de proiect și de comanda de vânzare.',
     '4.000 lei fără TVA · 840 lei TVA · 4.840 lei total.',
     'Selectezi furnizorul, produsele, cantitățile, prețurile și proiectul. Confirmi comanda. Facturarea este bazată pe cantitățile recepționate.'),
    ('04', 'Recepția în depozit', 'Inventar → Operații → Recepții', 'receipt',
     'Cele 10 panouri au fost recepționate integral. Documentul de recepție provine din comanda de achiziție.',
     'Recepție validată: 10 bucăți. Stocul a crescut cu 10.',
     'Deschizi recepția din comanda de achiziție, verifici cantitatea efectiv primită și apeși Validează. Abia apoi creezi factura furnizorului.'),
    ('05', 'Factura furnizorului', 'Achiziții → Facturi furnizor', 'vendor_bill',
     'Factura a fost creată din achiziție, cu cantitatea recepționată și distribuție analitică 100% pe proiect.',
     'Factura de 4.840 lei este contabilizată și plătită; rest de plată 0.',
     'Din achiziție apeși Creează factură, completezi data și referința furnizorului, verifici conturile și taxele și confirmi documentul.'),
    ('06', 'Execuție și pontaj', 'Proiect → Sarcini / Fișe de pontaj', 'project',
     'Alex Instalator [TEST] are 8 ore înregistrate pentru montaj, la un cost intern de 50 lei/oră. Montajul rămâne facturat la preț fix.',
     'Cost analitic al muncii: 400 lei. Nu este un stat de salarii.',
     'Pe sarcina de montaj adaugi fișa de pontaj, angajatul, descrierea și orele. La terminare marchezi sarcina Efectuat.'),
    ('07', 'Cheltuială → aprobare → decont', 'Cheltuieli', 'expense',
     'Deplasare fictivă de 200 lei, plătită inițial de angajat, fără TVA dedusă în acest exemplu. Are un document justificativ marcat explicit DEMO.',
     'Cheltuiala este aprobată, contabilizată și rambursată angajatului.',
     'Creezi cheltuiala, atașezi justificativul, alegi Angajat (pentru a rambursa) și proiectul. Urmează Trimitere → Aprobare → Contabilizare → Plată.'),
    ('08', 'Livrare și predarea lucrării', 'Inventar → Operații → Livrări', 'delivery',
     'Cele 10 panouri au fost livrate clientului, iar montajul și predarea au fost marcate finalizate.',
     'Livrare validată: 10 bucăți. Stoc final și rezervări: 0.',
     'Deschizi livrarea din comanda clientului, verifici cantitatea efectiv livrată și validezi. Documentele de stoc rămân legate de proiect.'),
    ('09', 'Factura clientului', 'Vânzări → Facturi', 'customer_invoice',
     'Factura este generată din comanda clientului: panourile după livrare, iar montajul la prețul fix convenit.',
     'Factura de 9.075 lei este contabilizată și încasată; rest de încasat 0.',
     'Din comandă apeși Creează factură, verifici produsele, taxele și conturile, apoi Confirmă. Nu am transmis factura în e-Factura/ANAF.'),
    ('10', 'Plăți și reconciliere bancară', 'Facturare → Bancă / documentele de plată', 'bank_statement',
     'Am înregistrat încasarea clientului, plata furnizorului și rambursarea angajatului, apoi le-am asociat cu tranzacțiile unui extras fictiv.',
     '3 plăți reconciliate. Extras complet și valid, cu sold final 14.035 lei.',
     'Înregistrezi plata pe fiecare document. Tranzacția de extras se potrivește cu plata din contul tranzitoriu; astfel factura trece din În plată în Plătit.'),
]

step_html = []
for number, title, menu, key, story, result, how in steps:
    extra = ''
    if number == '06':
        extra = anchor('Deschide pontajul de 8 ore', 'account.analytic.line', s['timesheet'], 'secondary')
    step_html.append(f'''<article class="step" id="pas-{number}">
      <div class="step-head"><span class="number">{number}</span><div><p class="eyebrow">{html.escape(menu)}</p><h2>{html.escape(title)}</h2></div><span class="done">Finalizat</span></div>
      <p>{html.escape(story)}</p><div class="result">{html.escape(result)}</div>
      <details><summary>Cum repeți această etapă</summary><p>{html.escape(how)}</p></details>
      <div class="links">{anchor('Deschide în Odoo', models[key], s[key], 'button')}{extra}<span class="doc">{html.escape(records[key])}</span></div>
    </article>''')

document_rows = ''.join(f'<tr><td>{html.escape(label)}</td><td>{anchor(records[key], models[key], s[key])}</td><td>{status}</td></tr>'
    for label, key, status in [('Proiect','project','Finalizat'),('Comandă client','sale','Confirmată · facturată integral'),
        ('Comandă furnizor','purchase','Confirmată · facturată integral'),('Recepție','receipt','Validată'),('Livrare','delivery','Validată'),
        ('Factură client','customer_invoice','Plătită'),('Factură furnizor','vendor_bill','Plătită'),('Cheltuială','expense','Rambursată'),('Extras bancar','bank_statement','Valid și reconciliat')])

summary = f'''<h2>Flux de test încheiat — TEST-PV-001</h2>
<p>Proiect, vânzare, achiziție, stoc, pontaj, cheltuială, facturi și plăți simulate. Toate cele patru sarcini sunt finalizate.</p>
<ul><li>Venituri fără TVA: 7.500 lei.</li><li>Materiale: 4.000 lei; deplasare: 200 lei; cost intern pentru 8 ore: 400 lei.</li>
<li>Marjă analitică: 2.900 lei (38,67%).</li><li>Factura clientului: 9.075 lei; factura furnizorului: 4.840 lei; decont: 200 lei. Toate plătite.</li>
<li>Stoc final: 0; soldul extrasului fictiv: 14.035 lei, inclusiv finanțare inițială de 10.000 lei.</li></ul>
<p>Cei 400 lei pentru pontaj sunt cost analitic estimat; nu s-a rulat salarizarea. Rezultatul contabil al documentelor înregistrate este 3.300 lei înainte de salarizare și impozit. Finanțarea inițială rămâne o datorie fictivă de 10.000 lei către asociat.</p>
<table><tbody>{document_rows}</tbody></table>
<p>DATE FICTIVE. Nu au fost trimise emailuri, documente ANAF sau plăți reale.</p>'''
update = c.ensure('project_update', 'project.update', {'name': 'TEST FINALIZAT - Rezultate si documente',
    'project_id': s['project'], 'status': 'done', 'progress': 100, 'description': summary})
c.write('project.update', update, {'description': summary})

page = f'''<!doctype html>
<html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GreenTech · Flux complet Odoo — test finalizat</title>
<style>
:root{{--ink:#152d36;--muted:#60747a;--green:#0c7662;--paper:#f3f6f4;--border:#dce5df}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}}
header{{background:#143b38;color:white;padding:54px max(24px,calc((100vw - 1120px)/2)) 44px}}header h1{{font-size:clamp(32px,4.5vw,54px);line-height:1.08;margin:14px 0 18px;letter-spacing:-1.6px}}header p{{max-width:800px;color:#cce0d7}}.kicker{{font-size:12px;font-weight:750;letter-spacing:2px;text-transform:uppercase;color:#99d8b9}}
.badge{{display:inline-block;padding:5px 12px;background:#d4f5df;color:#195b40;border-radius:99px;font-weight:700;font-size:12px}}main{{max-width:1168px;padding:28px 24px 64px;margin:auto}}a{{color:var(--green);text-underline-offset:3px}}.button{{display:inline-block;background:var(--green);color:white;text-decoration:none;font-weight:650;padding:10px 16px;border-radius:8px}}header .button{{background:#e4f6b2;color:#173d33}}.hero-links{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}}.hero-links a.secondary{{color:#e6f1eb}}.notice{{background:#fff;border:1px solid var(--border);border-left:4px solid var(--green);border-radius:10px;padding:18px 22px;margin-bottom:24px}}.notice p{{margin:5px 0}}code{{background:#eaf0ec;padding:2px 5px;border-radius:4px;font-size:.9em}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}}.metric{{background:white;border:1px solid var(--border);border-radius:12px;padding:20px}}.metric strong{{display:block;font-size:30px;line-height:1.3;letter-spacing:-.8px}}.metric span{{font-size:13px;color:var(--muted)}}.metric.emphasis{{background:#e4f1e8;border-color:#badbc6}}
.flow{{display:flex;gap:8px;flex-wrap:wrap;margin:28px 0 38px;font-size:13px;font-weight:650}}.flow span{{padding:7px 11px;background:#e3ebe5;border-radius:6px}}.flow b{{align-self:center;color:#87a093}}
.section-title{{font-size:26px;line-height:1.2;margin:36px 0 18px;letter-spacing:-.5px}}.step{{background:white;border:1px solid var(--border);border-radius:14px;padding:26px;margin-bottom:18px;scroll-margin-top:20px}}.step-head{{display:flex;align-items:center;gap:16px}}.number{{display:grid;place-items:center;min-width:46px;height:46px;background:#edf4e9;border-radius:11px;color:var(--green);font-size:20px;font-weight:750}}.eyebrow{{margin:0!important;color:var(--muted);font-size:12px}}h2{{margin:0;font-size:23px;line-height:1.3;letter-spacing:-.35px}}.done{{margin-left:auto;background:#edf7ed;color:#2e6b3c;padding:4px 10px;border-radius:99px;font-size:11px;font-weight:750}}.step p{{max-width:960px}}.result{{padding:12px 16px;background:#f0f6f2;border-radius:8px;color:#245746;font-weight:650}}details{{margin:16px 0}}summary{{cursor:pointer;font-weight:650;color:var(--muted)}}details p{{padding-left:18px;border-left:2px solid var(--border)}}.links{{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-top:20px}}.doc{{color:var(--muted);font-size:12px;overflow-wrap:anywhere}}.panel{{background:#fff;border:1px solid var(--border);border-radius:14px;padding:28px;margin:24px 0}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:12px 10px;border-bottom:1px solid var(--border);vertical-align:top}}th{{font-size:11px;letter-spacing:1px;text-transform:uppercase;color:var(--muted)}}.total{{font-size:17px;font-weight:750;background:#edf5ef}}.split{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.small{{font-size:13px;color:var(--muted)}}.checklist{{padding-left:22px}}.checklist li{{margin:8px 0}}footer{{font-size:12px;color:var(--muted);margin-top:32px}}nav{{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0}}.scroll-table{{overflow-x:auto}}@media(max-width:760px){{.metrics,.split{{grid-template-columns:1fr 1fr}}.step,.panel{{padding:18px}}.done{{display:none}}h2{{font-size:20px}}.split{{grid-template-columns:1fr}}.metric strong{{font-size:25px}}}}@media print{{body{{background:white}}header{{padding:24px}}main{{padding:12px}}.button,details,nav{{display:none}}.step,.panel{{break-inside:avoid}}a{{color:#152d36;text-decoration:none}}}}
</style></head><body>
<header><span class="kicker">GreenTech / Odoo 19 / Demonstrație completă</span><h1>De la proiect<br>la bani încasați.</h1><p>Un flux executat până la capăt în Odoo: lucrare fotovoltaică de 5 kW, aprovizionare, montaj, cheltuieli, livrare, facturi și reconciliere bancară.</p><div class="hero-links"><span class="badge">TEST FINALIZAT ȘI VERIFICAT</span><a class="button" href="{home}" target="_blank" rel="noopener">Deschide proiectul în Odoo ↗</a>{anchor('Raportul final din Odoo','project.update',update,'secondary')}</div></header>
<main><div class="notice"><p><strong>Începe cu <code>09-DESCHIDE-FLUX-TEST.cmd</code> din folderul ODDo.</strong> Scriptul copiază parola pentru această bază și deschide aplicația.</p><p>Baza: <code>{db}</code> · Utilizator: <code>admin</code> · La Password lipește cu <strong>Ctrl+V</strong>. Parola bazei de test diferă de cea din EMI.</p><p class="small">Scenariul folosește exclusiv date fictive. EMI a rămas separată. Nu există plăți bancare reale, emailuri trimise sau documente transmise ANAF.</p></div>
<div class="metrics"><div class="metric"><span>VENITURI FĂRĂ TVA</span><strong>7.500 lei</strong><span>panouri + montaj</span></div><div class="metric"><span>COSTURI DE PROIECT</span><strong>4.600 lei</strong><span>materiale + deplasare + timp</span></div><div class="metric emphasis"><span>MARJĂ ANALITICĂ</span><strong>2.900 lei</strong><span>38,67% din venituri</span></div><div class="metric"><span>REST PE DOCUMENTE</span><strong>0 lei</strong><span>client, furnizor și decont</span></div></div>
<nav><a href="#etape">Cele 10 etape</a><a href="#rezultat">Rezultatul financiar</a><a href="#documente">Documentele create</a><a href="#verificari">Ce am verificat</a></nav>
<div class="flow"><span>Proiect</span><b>→</b><span>Ofertă</span><b>→</b><span>Achiziție</span><b>→</b><span>Recepție</span><b>→</b><span>Montaj & cheltuieli</span><b>→</b><span>Livrare</span><b>→</b><span>Facturare</span><b>→</b><span>Plăți & închidere</span></div>
<h2 class="section-title" id="etape">Parcurge documentele în ordinea lucrării</h2>
<p class="small">Documentele sunt deja finalizate. Butoanele le deschid pentru verificare. „Cum repeți această etapă” explică acțiunile pentru un proiect nou; nu reconfirma documentele acestui test.</p>
{''.join(step_html)}
<h2 class="section-title" id="rezultat">De ce marja și soldul băncii sunt diferite</h2>
<div class="split"><section class="panel"><h2>Rezultatul proiectului</h2><table><tbody><tr><td>Venituri din panouri</td><td>6.000 lei</td></tr><tr><td>Venituri din montaj</td><td>1.500 lei</td></tr><tr><td>Cost panouri</td><td>−4.000 lei</td></tr><tr><td>Deplasare</td><td>−200 lei</td></tr><tr><td>Cost intern pontaj: 8 h × 50 lei</td><td>−400 lei</td></tr><tr class="total"><td>Marjă analitică</td><td>2.900 lei</td></tr></tbody></table><p class="small">Pontajul adaugă un cost analitic estimat. Nu am creat stat de salarii sau plata salariului. Documentele contabilizate dau un rezultat de 3.300 lei înainte de salarizare și impozit.</p></section>
<section class="panel"><h2>Extrasul bancar fictiv</h2><table><tbody><tr><td>Finanțare inițială de la asociat</td><td>10.000 lei</td></tr><tr><td>Încasare client, cu TVA</td><td>+9.075 lei</td></tr><tr><td>Plată furnizor, cu TVA</td><td>−4.840 lei</td></tr><tr><td>Rambursare angajat</td><td>−200 lei</td></tr><tr class="total"><td>Sold final</td><td>14.035 lei</td></tr></tbody></table><p class="small">Finanțarea de 10.000 lei rămâne datorie fictivă către asociat. Diferența de TVA din exemplu este 735 lei; nu este achitată și nu reprezintă o declarație fiscală depusă.</p></section></div>
<section class="panel" id="documente"><h2>Registrul documentelor de test</h2><div class="scroll-table"><table><thead><tr><th>Etapă</th><th>Document Odoo</th><th>Rezultat</th></tr></thead><tbody>{document_rows}</tbody></table></div><p class="small">În fiecare document poți urmări butoanele către comandă, factură, recepție/livrare, proiect sau plată.</p></section>
<section class="panel" id="verificari"><h2>Verificări executate</h2><ul class="checklist"><li>Facturile și decontul sunt contabilizate, plătite și au rest zero.</li><li>Toate notele contabile înregistrate sunt echilibrate: debit = credit.</li><li>Recepția și livrarea au câte 10 panouri; stocul și rezervările finale sunt zero.</li><li>Cele trei plăți sunt reconciliate cu extrasul; conturile de plăți/încasări în curs au sold zero.</li><li>Toate cele patru sarcini sunt finalizate; pontajul are 8 ore și cost 400 lei.</li><li>Panoul nativ al proiectului și calculul independent confirmă marja de 2.900 lei.</li><li>Formularele, fișierele CSS/JavaScript și previzualizările HTML ale documentelor răspund corect.</li></ul><p class="small">Verificări prin HTTP/RPC și reconciliere independentă în baza de date. Nu s-a efectuat inspecție vizuală într-un browser controlat automat. Jurnalul complet este în <code>logs/workflow-verification.json</code>.</p></section>
<footer>Creat la {datetime.now().strftime('%d.%m.%Y %H:%M')} · Odoo 19 Community · Demonstrație locală, fără valoare fiscală.<br>TVA și conturile sunt cele folosite în exemplu; configurarea pentru activitatea reală trebuie stabilită separat. <a href="https://www.odoo.com/documentation/19.0/applications/services/project/project_management/project_profitability.html">Documentație Odoo: profitabilitatea proiectului</a>.</footer>
</main></body></html>'''
(ROOT / 'GHID-FLUX-COMPLET-ODOO.html').write_text(page, encoding='utf-8')
print('Guide saved: GHID-FLUX-COMPLET-ODOO.html')
print('Native Odoo walkthrough:', home)

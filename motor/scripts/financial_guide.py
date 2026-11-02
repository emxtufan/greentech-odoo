"""Build the Romanian guide from verified sandbox IDs and independent totals."""
import base64
from html import escape
import json
from financial_client import Client, ROOT

c = Client()
s = c.state
v = json.loads((ROOT / 'logs/financial-verification.json').read_text(encoding='utf-8'))
t = v['summary']
money = lambda x: f'{x:,.2f}'.replace(',', ' ').replace('.', ',') + ' lei'
url = lambda path: c.base + '/odoo/' + path + '?db=greentech_financiar_test'
link = lambda path,label: f'<a href="{escape(url(path),quote=True)}" target="_blank" rel="noopener">{escape(label)} ↗</a>'

sections = [
('01', 'Facturi către clienți', '12 facturi fictive: 10 validate și 2 ciorne. Ai exemple achitate, restante, una achitată parțial și una anulată prin storno.',
 [('customer-invoices','Toate facturile'),(f'customer-invoices/{s["sale_0"]}','Factură achitată'),
  (f'customer-invoices/{s["sale_4"]}','Plată parțială'),(f'customer-invoices/{s["sale_10"]}','Ciornă pentru exercițiu')],
 'Deschide ciorna, verifică partenerul, liniile și TVA-ul, apoi apasă Confirmă. Folosește doar baza DEMO.'),
('02', 'Storno și trasabilitate', 'Nota de credit a fost generată din factura originală, validată și reconciliată cu aceasta. Soldul celor două documente este zero.',
 [(f'customer-invoices/{s["sale_8"]}','Factura anulată'),(f'customer-credit-notes/{s["credit_note"]}','Nota de credit')],
 'Dintr-o factură validată, folosește Nota de credit / Storno. Verifică documentul și legătura cu factura inițială.'),
('03', 'Facturi de furnizor', '9 facturi de furnizor, inclusiv achiziția mijlocului fix. Există documente plătite, restante și o ciornă.',
 [('vendor-bills','Toate facturile furnizor'),(f'vendor-bills/{s["purchase_0"]}','Furnizor achitat'),
  (f'vendor-bills/{s["asset_bill"]}','Achiziție mijloc fix')],
 'Verifică data, referința furnizorului, contul de cheltuială sau imobilizare și taxele. Confirmă înainte de înregistrarea plății.'),
('04', 'Bancă, încasări și plăți', '9 plăți/încasări fictive sunt legate de documente și de extrase. Finanțarea inițială de 100.000 lei este o datorie către asociat, nu un venit.',
 [('customer-payments','Încasări'),('vendor-payments','Plăți furnizori'),
  (f'action-{c.ref("account.open_account_journal_dashboard_kanban")}','Jurnale și reconciliere')],
 'În factură folosește Înregistrează plata. În jurnalul bancar potrivește apoi tranzacția din extras cu plata; simpla înregistrare a plății nu înlocuiește reconcilierea.'),
('05', 'Casa și centrele de cost', 'Transfer fictiv bancă → casă: 2.000 lei; cheltuială de transport fără TVA dedusă: 150 lei. Centre analitice: Administrativ, Operațiuni, Comercial.',
 [(f'action-{c.ref("account.open_account_journal_dashboard_kanban")}','Deschide jurnalul Casa DEMO RON'),('entries','Note contabile')],
 'Soldul casei este 1.850 lei. În liniile de factură poți selecta distribuția analitică pentru urmărirea cheltuielilor pe centre de cost.'),
('06', 'Mijloace fixe și amortizare', 'Server fictiv de 12.000 lei, creat automat din factura de furnizor. Plan de 24 luni × 500 lei; prima amortizare este înregistrată la 31.10.2026.',
 [(f'action-{c.ref("account_asset_management.account_asset_action")}/{s["asset"]}','Registrul mijlocului fix'),
  (f'entries/{s["depreciation_move"]}','Nota de amortizare')],
 'Verifică profilul, conturile și data de început înainte de validarea activului. Exemplul folosește o durată aleasă pentru demonstrație, nu o recomandare fiscală.'),
('07', 'Rapoarte și buget', 'Balanță, carte mare, registru jurnal, raport TVA, scadențe, profit și pierdere, situație patrimonială și comparație cu bugetul. Exporturile Excel au fost generate și verificate.',
 [(f'action-{s["action_pnl_report"]}','Profit și pierdere'),(f'action-{s["action_balance_report"]}','Situație patrimonială'),
  (f'action-{s["action_budget_report"]}','Realizat / buget'),
  (f'action-{c.ref("account_financial_report.action_trial_balance_wizard")}','Balanță')],
 'În rapoartele OCA setează 01.10.2026–31.10.2026 și numai înregistrările validate. Situația patrimonială include și achiziția din septembrie. Bugetul de profit este 24.200 lei.'),
('08', 'Închiderea perioadei', 'Sunt pregătite două modele: închiderea veniturilor și închiderea cheltuielilor. Testul tranzacțional a transferat corect 5.200 lei în contul 121 și a fost anulat după verificare.',
 [(f'action-{c.search("ir.actions.act_window",[("res_model","=","l10n.ro.account.period.closing")],["name"],limit=1)[0]["id"]}','Modele de închidere')],
 'Luna este încă deschisă. La închidere verifică mai întâi toate documentele, apoi generează închiderile și aplică data de blocare. Nu executa repetat aceeași închidere.'),
]
cards = ''.join(f'<section class="card" id="pas-{n}"><div class="number">{n}</div><h2>{escape(title)}</h2><p>{escape(desc)}</p><div class="links">'+''.join(link(path,label) for path,label in links)+f'</div><p class="try"><b>Exercițiu:</b> {escape(exercise)}</p></section>' for n,title,desc,links,exercise in sections)
exports = [('balanta','Balanță'),('carte_mare','Carte mare'),('registru_jurnal','Registru jurnal'),('tva','Raport TVA'),
    ('scadente_clienti','Scadențe clienți'),('pnl_report','Profit și pierdere'),('balance_report','Situație patrimonială'),
    ('budget_report','Realizat și buget'),('mijloace_fixe','Mijloace fixe')]
export_links = ''.join(f'<a href="logs/financial-exports/{name}.xlsx">{escape(label)} · XLSX</a>' for name,label in exports)
pdf_text = ('Motorul PDF nu este instalat. Rulează 11-INSTALEAZA-PDF.cmd, finalizează instalarea, apoi 12-REPORNESTE-FINANCIAR.cmd. '
    'Până atunci, folosește rapoartele web și exporturile Excel. Instalatorul este verificat prin SHA-256 înainte de execuție.') if v['limitations']['pdf_engine'] != 'ok' else 'Motorul PDF este instalat. Consultă raportul de verificare pentru documentele testate.'
page = f'''<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GreenTech · Financiar DEMO</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f3;color:#1a3029;font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}}main{{max-width:1160px;margin:auto;padding:44px 24px}}header{{padding:40px;border-radius:24px;background:#123e32;color:#fff}}.tag{{font-size:12px;letter-spacing:2px;color:#b9e4cd}}h1{{font-size:clamp(32px,5vw,52px);line-height:1.12;margin:15px 0}}header p{{max-width:810px;color:#e0eee7}}header a{{background:#dcf58c;color:#173d2d;padding:12px 18px;border-radius:8px;display:inline-block;text-decoration:none;font-weight:650}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:22px 0}}.stat{{background:white;border:1px solid #dce5df;padding:20px;border-radius:14px}}.stat strong{{display:block;font-size:24px;line-height:1.4}}.stat span{{font-size:13px;color:#53675e}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card{{padding:26px;background:white;border:1px solid #dce5df;border-radius:16px}}.number{{font:700 13px system-ui;color:#35735b}}h2{{font-size:23px;line-height:1.25;margin:9px 0 14px}}.links{{display:flex;flex-wrap:wrap;gap:8px}}.links a,.downloads a{{color:#15523c;border:1px solid #d6e7dd;border-radius:7px;padding:7px 10px;text-decoration:none;font-size:14px;background:#f7faf8}}a:hover{{text-decoration:underline}}.try{{font-size:14px;color:#54665d;border-top:1px solid #e5ebe7;padding-top:14px;margin-bottom:0}}.notice{{padding:25px;border-radius:14px;background:#fff1d7;margin:24px 0;color:#574316}}.downloads{{display:flex;gap:10px;flex-wrap:wrap}}footer{{font-size:13px;color:#5c6e64;margin-top:28px}}code{{background:#e7eee8;padding:2px 5px;border-radius:4px;color:#254032}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}.stats{{grid-template-columns:1fr 1fr}}header{{padding:26px}}main{{padding:20px 14px}}.stat strong{{font-size:20px}}}}@media print{{body{{background:white}}main{{padding:0}}.card{{break-inside:avoid}}.grid{{display:block}}.card{{margin-bottom:15px}}header{{background:white;color:black}}header p{{color:black}}}}</style></head>
<body><main><header><div class="tag">GREENTECH / ODOO 19 + OCA / OCTOMBRIE 2026</div><h1>Financiar, de la factură<br>până la balanță.</h1><p>Mediu separat de exercițiu, cu parteneri și documente fictive. Facturi, încasări, plăți, casă, amortizare și rapoarte legate de aceleași înregistrări contabile.</p>{link('', 'Deschide Financiar DEMO')}</header>
<p><b>Acces rapid:</b> rulează <code>10-DESCHIDE-FINANCIAR-DEMO.cmd</code>. Pornește serverul dacă este oprit și copiază parola. Utilizator: <b>admin</b>; lipește parola cu <b>Ctrl+V</b>. Baza: <code>greentech_financiar_test</code>, port <b>8070</b>.</p>
<div class="stats"><div class="stat"><span>Rezultat înainte de impozit</span><strong>{money(t['profit'])}</strong></div><div class="stat"><span>Sold bancă fictivă</span><strong>{money(t['bank'])}</strong></div><div class="stat"><span>De încasat de la clienți</span><strong>{money(t['customer_receivable'])}</strong></div><div class="stat"><span>De plătit furnizorilor</span><strong>{money(t['supplier_payable'])}</strong></div></div>
<p>Venituri: <b>{money(t['revenue'])}</b> · Cheltuieli: <b>{money(t['costs'])}</b> · Casă: <b>{money(t['cash'])}</b> · Mijloc fix net: <b>{money(t['asset_net'])}</b>. Cifrele includ amortizarea demonstrativă din 31 octombrie.</p>
<div class="grid">{cards}</div>
<div class="notice"><h2>Limitele acestui test</h2><p>{escape(pdf_text)}</p><p>Acest pachet nu include salarizare românească, generarea completă D300/D394/D390/D112/D406 sau bilanțul oficial ANAF. Raportul TVA și situația patrimonială sunt rapoarte contabile, nu declarații gata de depus. e-Factura este disponibilă ca modul de bază, dar nu este conectată la SPV.</p><p>Nu sunt conectate bănci și nu au fost trimise mesaje, plăți ori declarații. Verificările sunt prin HTTP/RPC, rapoarte și reconciliere independentă în baza de date; nu s-a putut face inspecție vizuală în browser.</p></div>
<h2>Exporturi din scenariul verificat</h2><p>Aceste fișiere sunt instantanee. După modificarea datelor, generează din nou raportul în Odoo.</p><div class="downloads">{export_links}</div>
<footer>Verificare: {escape(v['verified_at'])} · {len(v['checks'])} verificări trecute. Surse: Odoo Community + module OCA 19.0, versiuni fixate. Instalația EMI și demonstrația de proiect au fost păstrate separat.</footer></main></body></html>'''
target = ROOT / 'GHID-FINANCIAR-DEMO.html'
target.write_text(page,encoding='utf-8')
attachment_id = c.ensure('guide_attachment','ir.attachment',{'name':target.name,'datas':base64.b64encode(page.encode()).decode(),
    'mimetype':'text/html','description':'Ghid local pentru demonstratia financiara; date fictive.'})
c.write('ir.attachment', attachment_id, {'datas':base64.b64encode(page.encode()).decode()})
print('Created Romanian financial guide:',target.name)

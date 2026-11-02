# GreenTech — Odoo 19, codul tău (ghid complet)

Acest folder conține **codul tău** (cele 14 module Odoo, în `module\`) și, alături, **motorul**: programul Odoo, Python-ul și datele, în `motor\`. `motor\` nu se editează niciodată — se poate actualiza și ai pierde modificările.
Separarea e simplă: tu scrii numai în `module\`; `motor\` conține sursele Odoo, Python-ul și datele bazei.
Nu trebuie să înveți Odoo ca să pornești — dublu-clic pe `porneste.py` și gata.

---

## 1. Cum pornești

1. **Dublu-clic pe `porneste.py`** (din acest folder). Din terminal, în acest folder, comanda echivalentă este:

   ```
   python porneste.py
   ```

2. Se deschide o fereastră de consolă — acolo rulează serverul. **Lasă-o deschisă** cât lucrezi. Dacă o închizi, Odoo se oprește.
3. Scriptul așteaptă până când serverul răspunde pe portul **8069** (maxim 120 de secunde), apoi **deschide singur browserul** pe **http://127.0.0.1:8069/odoo?db=EMI**. Dacă Odoo rulează deja, browserul se deschide imediat.
4. În browser: baza de date **EMI**, utilizator **admin**.

Despre parolă: scriptul **copiază parola contului `admin` în clipboard** și afișează în consolă
`Utilizator: admin, parola copiata – CTRL+V`. În pagina de login dai click în câmpul *Password*
și lipești cu **CTRL+V**. Parola nu este afișată pe ecran, dar este în clipboard — după login
copiază alt text ca să o scoți de acolo. Datele de acces sunt salvate în
`motor\config\acces-local.json` (nu publica acest fișier).

**Oprire:** click în fereastra **Odoo**, apasă **CTRL+C**. Nu închide fereastra cu X cât timp
serverul scrie în bază.

**Dacă apare `[EROARE] Nu gasesc ...`:** mesajul îți spune exact ce lipsește din `motor\`
(Python-ul din `motor\.venv`, sursele din `motor\odoo` sau configurarea `motor\config\odoo.conf`)
și ce script de instalare trebuie rulat. **Dacă apare `[ATENTIE] Odoo nu a raspuns pe portul 8069`:**
uită-te mai sus în aceeași fereastră — acolo este eroarea reală (PostgreSQL oprit, port ocupat,
configurație lipsă); jurnalul complet este în `motor\logs\odoo.log`.

### Actualizarea unui modul (după ce schimbi fișiere XML, câmpuri sau `__manifest__.py`)

Oprește serverul (**CTRL+C**) și rulează, din acest folder:

```
python porneste.py -d EMI -u <modul> --stop-after-init
```

Scrie numele tehnic al modulului în locul lui `<modul>` (ex. `greentech_demo`). Comanda
actualizează **un singur modul**, apoi iese singură. După ea, pornește normal cu
`python porneste.py` (sau dublu-clic).

Dacă nu actualizezi modulul după ce schimbi fișiere XML (formulare, meniuri, câmpuri),
modificarea **nu apare** în Odoo. Modificările doar în Python se văd, de obicei, la o simplă
repornire, dar actualizarea modulului este varianta sigură.

---

## 2. Structura folderului

```
GreenTech-Odoo\
  porneste.py       <- dublu-clic aici ca sa pornesti Odoo (sau python porneste.py)
  CITESTE-MA.md     <- ghidul scurt
  CITESTE.md        <- acest ghid
  module\           <- CODUL TAU: modulele Odoo
    greentech_anaf_d112\
      __manifest__.py
      models\
      views\
      services\
      static\
      tests\
      security\
    greentech_anaf_d300\
    ... (14 module in total, vezi §3)
  motor\            <- MOTORUL: nu se editeaza niciodata
    odoo\           <- sursele Odoo 19 (server, ORM, module standard)
    .venv\          <- Python-ul si pachetele instalate (mediul Odoo)
    config\         <- odoo.conf (port 8069, baza EMI, addons_path) + acces-local.json
    data-runtime\   <- date si atasamente (filestore); aici se salveaza fisierele urcate
    logs\           <- jurnalul pornirii (odoo.log); aici te uiti cand ceva nu merge
    scripts\        <- scripturile PowerShell apelate de fisierele .cmd vechi
    tools\          <- unelte auxiliare ale motorului
    third_party_addons\ <- module OCA / terte, instalate in Odoo
    deploy\         <- scripturi de instalare/actualizare pe server
    *.html          <- ghidurile HTML vechi (D300-GHID.html, JURNALE-TVA-GHID.html, ...)
    *.cmd           <- fisierele .cmd vechi (pastrate pentru scripturile existente)
  .ai\              <- fisiere asistent: NU le atinge
  .claude\          <- fisiere asistent: NU le atinge
  .codex\           <- fisiere asistent: NU le atinge
  CLAUDE.md         <- instructiuni asistent: NU il atinge
  AGENTS.md         <- instructiuni asistent: NU il atinge
  .mcp.json         <- configurare asistent: NU o atinge
```

Regulă simplă: **scrii doar în `module\`**. Restul (Odoo, `.venv`, baza de date, scripturile
vechi) este „motorul” și nu se editează. Fișierele de asistent din rădăcină (`.ai`, `.claude`,
`.codex`, `CLAUDE.md`, `AGENTS.md`, `.mcp.json`) sunt ale uneltelor, nu ale proiectului — nu le
atinge.

**Backup:** Odoo = baza PostgreSQL **și** folderul `motor\data-runtime` (filestore).
Copierea doar a `module\` nu salvează datele din Odoo.

---

## 3. Cele 14 module din `module\`

Numele din coloana „Dosar” este numele tehnic al modulului (așa apare în `__manifest__.py`).
„Ce face” este luat din `name` / `summary` / `README`.

### Contabilitate și TVA

| Dosar | Ce face |
|---|---|
| `greentech_ro_vat_journals` | Jurnale TVA România — cumpărări și vânzări: registru TVA cu PDF. |
| `greentech_anaf_d300` | ANAF — D300 Decont TVA 2026: calcule din contabilitate, regularizări, XML și validare ANAF. |
| `greentech_closing_feedback` | Confirmarea închiderii contabile: verifică intervalul și soldurile înainte de nota de închidere, apoi deschide nota generată. |
| `greentech_ro_advances` | Avansuri clienți și furnizori România: creare, repartizare pe facturi, raport. |

### Declarații ANAF

| Dosar | Ce face |
|---|---|
| `greentech_anaf_d112` | ANAF — Declarația 112: angajator, asigurați, XML, validare oficială și dosarul declarației. |
| `tbs_anaf_duk_validator` | ANAF DUKIntegrator: rulează validatorul oficial Java pe un XML deja generat (D100, D101, D112, D205, D300, D394) și întoarce verdict + PDF de confirmare. Nu generează declarații. |
| `tbs_saft_d406` | Romania SAF-T D406: generează declarația D406 (SAF-T) pe Odoo Community. |
| `greentech_tbs_integration` | Integrare SAF-T și e-Transport: leagă D406, validatorul DUK, e-Transport și D112 într-un singur flux. |

### Salarii

| Dosar | Ce face |
|---|---|
| `greentech_ro_payroll` | ANAF — State salariale România: calcul salarial din contractele Odoo și generare D112. |
| `greentech_hr_payroll_demo` | Diurne și salarizare DEMO: angajați fictivi, delegații/deconturi, pontaje, concedii, fluturași HTML/XLSX. Scenariu demonstrativ, nu motor fiscal complet. |

### Stocuri / eTransport

| Dosar | Ce face |
|---|---|
| `l10n_ro_edi_stock_extension` | Romania — eTransport Extension: corecții și extensii pentru eTransport ANAF v2.0.2 pe transferuri și transferuri în lot. |

### Import SAGA

| Dosar | Ce face |
|---|---|
| `greentech_saga_import` | Import SAGA — firme, documente și istoric contabil dintr-un backup `.fdb`. |

### Demo / compatibilitate

| Dosar | Ce face |
|---|---|
| `greentech_demo` | GreenTech Demo — Echipamente: exemplu minim editabil (evidența echipamentelor). |
| `greentech_mis_compat` | MIS Odoo 19 compatibility: patch pentru widgetul de rapoarte MIS Builder pe Odoo 19. |

---

## 4. Anatomia unui modul Odoo

Un modul este un folder cu nume unic. Structura tipică:

```
nume_modul\
  __manifest__.py     <- "buletinul" modulului: name, version, depends, data, assets
  __init__.py         <- importa pachetele Python (models, services, wizards)
  models\             <- tabelele si logica de business (models.Model, campuri, constrangeri)
  views\              <- XML: formulare, liste, meniuri, actiuni
  services\           <- logica pura, fara baza de date (calcul, XML, PDF) - usor de testat
  wizards\            <- ferestre temporare (TransientModel), ex. un export
  static\             <- JavaScript/Owl, SCSS, imagini (static/src/, static/description/)
  tests\              <- teste automate
  security\           <- ir.model.access.csv (drepturi pe model) + security.xml (grupuri, reguli)
  data\, migrations\  <- date initiale si scripturi de migrare intre versiuni
  README.md / readme\ <- documentatia modulului
```

Nu toate folderele există în toate modulele — un modul mic poate avea doar
`models.py` și `views/` (exemplu: `greentech_closing_feedback`).

**De unde începi să citești un modul (în ordinea asta):**

1. **`__manifest__.py`** — ce dependențe are (`depends`), ce fișiere XML încarcă (`data`),
   ce resurse front-end are (`assets`). Îți spune din prima ce module trebuie instalate.
2. **`models\`** — aici sunt datele și regulile: ce tabele există, ce câmpuri au, ce
   metode se apelează la confirmare/validare. Începe cu fișierul cel mai mare.
   Dacă modulul are `services\`, citește-l după `models\`: acolo stă calculul propriu-zis
   (XML, PDF, formule), separat de baza de date.
3. **`views\`** — ce vede utilizatorul: formulare, liste, meniuri. Aici găsești textul
   butoanelor și al coloanelor din ecran.
4. **`security\`** — cine are voie la ce (utilizator intern, grupuri, reguli).
5. **`tests\`** — cele mai bune exemple de utilizare: arată cum se creează un document
   și ce rezultat trebuie să iasă.

---

## 5. `motor\custom_addons`

`motor\custom_addons` este o **legătură (junction)** care arată spre `module\` din acest folder, păstrată pentru scripturile vechi din `motor\` — **nu o șterge**.

# GreenTech — Odoo 19 Community, surse Python pe Windows 10/11 (FARA Docker)

## Extindere OCA România instalată (20.10.2026)

Instanța financiară locală de pe portul **8070** are acum **150 de module instalate**, cu **58 de module noi**, incluzând dependențele Odoo. Pachetul selectat conține 30 de module OCA România și 6 module OCA pentru import bancar; 3 module România erau deja prezente. Include mesaje SPV, TVA la încasare, TVA nedeductibilă, verificare fiscală/CUI, localități, registre bancă/casă, chitanțe, importuri MT940/CAMT/CSV/XLSX și documente contabile de stoc/DVI.

Starea curentă și lista completă: [STARE-INSTALARE-OCA-RO.html](STARE-INSTALARE-OCA-RO.html). Lansatorul `10-DESCHIDE-FINANCIAR-DEMO.cmd` deschide acest raport și folosește configurația financiară actualizată. Cele 532 de înregistrări contabile, 1.646 de linii și 10 plăți au păstrat aceleași amprente pentru câmpurile contabile verificate. Au trecut verificarea 70 de vizualizări, factura HTML și accesul HTTP/RPC, meniurile și resursele CSS/JS.

Sursele fixate, backupul anterior, testele și patch-urile Windows sunt în `logs/oca-ro-install-20261020/`. Directorul activ pentru localizarea OCA este acum `third_party_addons/oca-ro-19`; cel anterior, `third_party_addons/l10n-romania`, este păstrat și nu mai figurează în configurația financiară. Nu reexecuta vechiul `financial_prepare.py` peste această bază: este un script de inițializare a demonstrației și poate înlocui configurația.

SPV/ANAF necesită configurarea accesului și verificarea fiscală ulterioară; nu s-au transmis documente și sarcinile programate sunt inactive. Registrul ANAF pentru TVA la încasare nu a fost descărcat, iar lipsa sa nu este marcată drept verificare reușită. D112, D300, D394 și D406/SAF-T nu au fost instalate ca generatoare de declarații. Serverul Linux nu a fost actualizat. Secțiunile de mai jos descriu etapele anterioare.

## Import SAGA reutilizabil (19.10.2026)

Modulul greentech_saga_import este instalat local pe portul 8070: **Financiar > Import SAGA > Importă backup .fdb**. DARIUSMED S.R.L. (CUI 22465902) este o firmă reală separată de GreenTech DEMO, importată din backupul confirmat de utilizator. Baza greentech_financiar_test conține acum și aceste date reale; nu trebuie tratată în întregime drept date fictive sau distribuită ca demonstrație.

Au fost verificate 111 documente, 453 note contabile și corespondența debit/credit pe 108 combinații cont/an. Detalii și limite: custom_addons/greentech_saga_import/README.md. Instalare pe server: deploy/financiar/IMPORT-SAGA.txt. Nu există sincronizare automată între datele locale și server.

## Demonstratie separata: numai financiar (19.10.2026)

Extensie ulterioara solicitata: **Financiar > Salarii si diurne**, pe aceeasi instanta 8070. Modulul `greentech_hr_payroll_demo` adauga trei angajati fictivi, delegatii/deconturi, pontaje, concedii, fluturasi si note/plati simulate. Octombrie este finalizat; noiembrie ramane in lucru. Documentele sunt imprimabile HTML si exportabile Excel. **Pregatirea D112 nu genereaza XML validat si nu depune declaratii. Salarizarea este un scenariu standard DEMO, nu un motor fiscal complet.** Limite si verificari: `custom_addons/greentech_hr_payroll_demo/README.md`, `logs/hr-payroll-verification.json`. Nu s-a creat niciun lansator nou.

Corectie Rapoarte DEMO: modulul local `greentech_mis_compat` adapteaza componenta MIS la Odoo 19. Configuratia se repara cu `scripts/financial_fix_demo_reports.py`: rezultat operational fara notele de inchidere, toate clasele de active/datorii si octombrie implicit la inchidere. Verificarea actuala a rapoartelor (dupa modificarile manuale ale utilizatorului) este in `logs/demo-reports-audit.json`; testul componentei JavaScript este in `logs/mis-widget-regression.json`. Acestea nu reprezinta un test vizual in browser. Detalii: `custom_addons/greentech_mis_compat/README.md`.

Ruleaza `10-DESCHIDE-FINANCIAR-DEMO.cmd`. Porneste instanta separata daca este oprita, copiaza parola contului `admin` si deschide ghidul. Adresa: http://127.0.0.1:8070/odoo?db=greentech_financiar_test . Configuratia este `config/odoo-financiar.conf`, iar accesul este salvat local in `config/acces-financiar-test.json` (exclus din Git).

Pachet: Odoo 19 Community + localizarea standard Romania + 17 module OCA pentru contabilitate, rapoarte, reconciliere, mijloace fixe, bugete si inchiderea perioadelor. Surse si commit-uri fixate: `logs/financial-package-sources.json`. Fisierele text au fost preluate prin conectorul GitHub si verificate dupa hash-ul Git; nu au fost incluse ilustratiile de marketing si traducerile pentru alte limbi. Copiile originale se gasesc in `logs/oca-financial-source-*.json`.

Scenariu fictiv: 6 clienti, 5 furnizori, 12 facturi clienti, 9 facturi furnizori (inclusiv mijlocul fix), 1 storno, 9 plati/incasari, extras bancar si casa reconciliate, activ de 12.000 lei cu 24 rate de amortizare a cate 500 lei. Doua facturi clienti si una de furnizor sunt ciorne pentru exercitii. Perioada de demonstratie este octombrie 2026, inclusiv amortizarea din 31 octombrie.

Ghid: `GHID-FINANCIAR-DEMO.html`. Verificari independente: `logs/financial-verification.json`; exporturile native HTML/XLSX sunt in `logs/financial-exports/`. Inchiderea lunii a fost verificata intr-o tranzactie anulata apoi, astfel incat luna de test ramane deschisa: `logs/financial-closing-test.json`. Backup PostgreSQL + filestore: calea curenta din `logs/financial-backup.json`.

Corectii locale documentate: in baza DEMO, conturile de amortizare cumulata 28xx sunt contra-active, iar 6811 este cheltuiala cu amortizarea; sursele OCA au doua directive QWeb actualizate si traduceri romanesti reparate. Patch-uri reproductibile si hash-uri: `scripts/financial_local_fixes.py`, `logs/financial-local-patches.json`. Revizuieste aceste corectii la actualizarea modulelor.

Limite explicite: nu s-a putut efectua inspectie vizuala in browser. Nu sunt incluse salarizarea romaneasca, declaratiile D300/D394/D390/D112/D406 complete sau bilantul oficial ANAF. Raportul TVA si situatia patrimoniala sunt rapoarte contabile/manageriale. SPV, SMTP si bancile reale nu sunt conectate; toate sarcinile programate sunt dezactivate in aceasta baza, iar serverul 8070 are `max_cron_threads=0`.

Motorul PDF lipseste la instalarea initiala. Pentru instalare: `11-INSTALEAZA-PDF.cmd` descarca instalatorul oficial si verifica SHA-256 din manifestul Microsoft winget; apoi `12-REPORNESTE-FINANCIAR.cmd` reporneste numai instanta financiara si ruleaza din nou verificarea (inclusiv PDF daca motorul este disponibil). Nu este necesara reinstalarea Odoo sau PostgreSQL.

Reproducere: `financial_prepare.py`, instalarea modulelor din `logs/financial-modules.json` cu configuratia financiara, `financial_local_fixes.py` si actualizarea modulului `account_financial_report`, apoi `financial_seed.py`, `financial_reports.py`, `financial_verify.py`, `financial_guide.py`. Scripturile de date refuza alte baze. Reexecutarea scenariului nu dubleaza documentele; nu il reexecuta dupa modificari manuale fara revizuirea datelor.

## Instalarea locala verificata la 19.10.2026

- Server: http://127.0.0.1:8069/odoo?db=EMI
- Baza activa: `EMI`; modulul `GreenTech Demo - Echipamente` este instalat.
- Pornire: `03-PORNESTE-ODOO.cmd`. Acces: `08-DESCHIDE-ODOO.cmd` (copiaza parola contului `admin`).
- Date active: `data-runtime/`; jurnal: `logs/odoo.log`.
- Raport de verificare: `logs/verificare-finala.json`.
- PostgreSQL 18 / Windows: `db_template = template1` evita combinatia incompatibila LC_COLLATE/LC_CTYPE.
- Corectie locala in `odoo/odoo/service/db.py`: `_drop_conn` selecteaza doar `backend_type = 'client backend'`, astfel incat sa nu incerce semnalizarea proceselor autovacuum. Revizuieste aceasta corectie dupa actualizarea surselor Odoo.
- Baza incompleta anterioara si directorul `data/` au fost pastrate. Detalii in `PORNIRE-SI-ACCES.txt`.

Verificate prin HTTP/RPC: creare baza, autentificare automata, persistenta sesiunii, pagini, pachete CSS/JS, meniuri/vizualizari si operatii pe echipamente. Nu s-a efectuat inspectie vizuala in browser; nu sunt incluse in aceasta verificare fiscalitatea, SMTP sau rapoartele PDF.


Acest kit instaleaza Odoo din **codul sursa oficial**: Python + PostgreSQL native pe Windows. Scop: **DEZVOLTARE SI TEST**, nu productie fiscala.

## Ce este in arhiva si ce se descarca la instalare

Arhiva contine scripturi, configuratii VS Code si un modul demo. **Nu contine intregul cod Odoo** (acesta este descarcat prin `git clone` cand rulezi scriptul 01).

```
GreenTech-Odoo19-Surse-Windows/
  01-INSTALEAZA-SURSE.cmd
  02-CONFIGUREAZA-POSTGRES.cmd
  03-PORNESTE-ODOO.cmd
  04-ACTUALIZEAZA-MODUL.cmd
  05-DESCHIDE-VSCODE.cmd
  06-DESCARCA-OCA-ROMANIA.cmd
  .vscode/launch.json
  custom_addons/greentech_demo/  <-- COD PYTHON/XML EDITABIL
  scripts/
  config/                      <-- odoo.conf se genereaza la pasul 02
  odoo/                        <-- repo oficial se descarca la pasul 01
  .venv/                       <-- mediu Python se genereaza la pasul 01
  data/                        <-- filestore local, generat dupa pornire
```

## Cerinte

- Windows 10/11 x64 cu acces la internet si 8 GB RAM sau mai mult (16 GB recomandat).
- **Python 3.12 x64**, cu Python Launcher `py`: https://www.python.org/downloads/windows/ . Pe installer bifeaza PATH si `py launcher`.
- **Git for Windows**: https://git-scm.com/download/win
- **PostgreSQL 16 x64**: https://www.postgresql.org/download/windows/ (inclusiv psql); la instalare pastreaza portul 5432, seteaza o parola pentru rolul `postgres` si noteaz-o.
- **VS Code** + extensia oficiala **Python** (si **Python Debugger**): https://code.visualstudio.com/
- Daca pip raporteaza erori de compilare, instaleaza **Visual Studio 2022 Build Tools**, componenta `Desktop development with C++`: https://visualstudio.microsoft.com/visual-cpp-build-tools/
- **Optional** pentru antet/subsol PDF: wkhtmltopdf 0.12.6; pentru limbi RTL: Node.js + `npm install -g rtlcss` (vezi documentatia oficiala Odoo). Nu sunt necesare pentru prima pornire web.

## Pasii de instalare

1. Descarca ZIP-ul, extrage intr-o cale simpla, de ex. `C:\GreenTech\Odoo19-dev` (evita OneDrive, nume cu caractere speciale, programe aflate in `Program Files`).
2. Instaleaza Python 3.12 x64, Git, PostgreSQL 16. Optional, ruleaza `00-VERIFICA-MEDIUL.cmd` pentru diagnosticul instalarii programelor.  **Deschide un terminal nou** dupa instalare. Verifica `py -3.12 --version` si `git --version`.
3. Ruleaza `01-INSTALEAZA-SURSE.cmd`. Scriptul descarca `https://github.com/odoo/odoo` pe branch `19.0`, creeaza `.venv` si instaleaza **exact dependentele** din `odoo\requirements.txt`. Daca apare eroare C++ la pip, instaleaza Build Tools si ruleaza din nou 01.
4. Ruleaza `02-CONFIGUREAZA-POSTGRES.cmd`. Introdu parola contului PostgreSQL `postgres` setata de tine la instalare. Scriptul creeaza rolul separat `greentech_odoo` (cu drept CREATEDB, fara superuser), testeaza autentificarea si genereaza `config\odoo.conf` cu parole aleatoare.
5. Ruleaza `03-PORNESTE-ODOO.cmd` si lasa fereastra deschisa. Deschide **http://127.0.0.1:8069**.
6. Creeaza baza `greentech_test`. **Master Password** este `admin_passwd` din `config\odoo.conf`. Seteaza un email si o alta parola pentru adminul web; alege tara Romania si bifeaza date demo daca vrei.
7. In Odoo activeaza modul dezvoltator, intra la Apps si foloseste `Update Apps List`; cauta si instaleaza **GreenTech Demo - Echipamente**. Exemplul apare in meniul GreenTech.
8. Daca ai modificat fisierele XML/modelul, opreste Odoo din terminal cu Ctrl+C, ruleaza `04-ACTUALIZEAZA-MODUL.cmd` si porneste din nou Odoo.
9. `05-DESCHIDE-VSCODE.cmd` deschide proiectul. In VS Code, `Run and Debug` -> `GreenTech: Odoo 19 (Python debug)` -> F5; **nu porni si scriptul 03 simultan** pe acelasi port.

## Optional: localizare Romania

Ruleaza `06-DESCARCA-OCA-ROMANIA.cmd`. Cloneaza `https://github.com/OCA/l10n-romania` branch `19.0` sub `third_party_addons\l10n-romania` si adauga folderul la `addons_path`. Repornieste Odoo, apoi actualizeaza lista aplicatiilor.

**ATENTIE:** doar descarcarea surselor OCA NU inseamna ca toate modulele sunt instalate sau compatibile impreuna. Unele cer module din alte repo-uri OCA; contabilitatea romaneasca, e-Factura si SAF-T trebuie testate individual, iar SAF-T complet nu este inclus aici.

## Ce modifici / unde e codul?

- `odoo/` = codul oficial Python (server, ORM si module de baza), XML, JavaScript si SCSS/CSS. Se poate citi si depana; evita modificarea nucleului, ca sa poti actualiza versiunea.
- `custom_addons/greentech_demo/models/equipment.py` = exemplu Python editabil (adaugare camp, reguli de business etc.).
- `custom_addons/greentech_demo/views/equipment_views.xml` = formulare, liste si meniu GreenTech.
- `custom_addons/greentech_demo/__manifest__.py` = dependinte, metadate si fisierele modulului.
- `custom_addons/greentech_demo/security/ir.model.access.csv` = permisiuni (demo: utilizatori interni au citire/scriere/creare/stergere; in productie defineste roluri specifice).
- `.vscode/launch.json` = debugger pentru Odoo pornit din surse.

Exemplu: schimba in `equipment.py` `string="Numar de serie"` in `string="Cod intern GreenTech"`, apoi actualizeaza modulul pentru a reimporta descrierile/vizualizarile.

## Troubleshooting

- `py -3.12` nu exista: instaleaza Python **3.12** pe 64-bit si Python Launcher; nu folosi automat o versiune mai noua.
- `git` nu e gasit: instaleaza Git for Windows si redeschide terminalul.
- `Microsoft Visual C++ 14.x required` / `failed building wheel`: instaleaza `Desktop development with C++`; reporneste terminalul si pasul 01.
- `FATAL password authentication failed`: verifica parola de `postgres` la pasul 02; daca ai deja `config\odoo.conf`, nu recrea rolul fara sa intelegi impactul.
- `could not connect to server`: porneste serviciul Windows PostgreSQL (Services / `services.msc`) si verifica portul 5432.
- Port 8069 ocupat: opreste alte instante Odoo; poti schimba `http_port` din `config\odoo.conf`.
- Modulul GreenTech nu apare: activeaza Developer Mode, Apps -> Update Apps List; elimina filtrul Apps daca e cazul, verifica `addons_path` din conf.
- `Permission denied` la fisiere: muta kitul in `C:\GreenTech\Odoo19-dev`, nu in Program Files.
- PDF incomplet: este posibil sa fie nevoie de wkhtmltopdf si fonturi adecvate; nu blocheaza dezvoltarea serverului.
- **Nu publica `config\odoo.conf`**, nu importa date reale pentru teste si nu expune portul 8069 pe Internet. Backup Odoo = backup PostgreSQL **si** directorul `data/` (filestore); pentru datele de test foloseste si managerul de backup.

## Comenzi echivalente (manual)

```powershell
# Din directorul kitului, dupa instalarea Python/Git/PostgreSQL si configurarea DB:
git clone --depth 1 --branch 19.0 https://github.com/odoo/odoo.git odoo
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\odoo\requirements.txt
.\.venv\Scripts\python.exe .\odoo\odoo-bin -c .\config\odoo.conf --dev=xml,reload
```

## Referinte oficiale

- https://www.odoo.com/documentation/19.0/administration/on_premise/source.html
- https://github.com/odoo/odoo/tree/19.0
- https://github.com/OCA/l10n-romania/tree/19.0
- https://www.odoo.com/documentation/19.0/developer/tutorials/server_framework_101.html

Verificarea kitului initial a fost statica. Instalarea locala a fost ulterior executata si verificata functional; vezi sectiunea de la inceput.

Acest kit este un starter independent creat pentru GreenTech; sursele Odoo si OCA se descarca de la autorii oficiali. Instalarea locala pe Windows a fost reparata si verificata conform sectiunii de la inceput.

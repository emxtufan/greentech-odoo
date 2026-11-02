# Salarii si diurne - demonstratie pe 8070

Modul local instalat in baza existenta `greentech_financiar_test`. Nu creeaza alte servere,
porturi, baze sau lansatoare. Meniul este **Financiar > Salarii si diurne**.

## Continut livrat

- Odoo nativ: angajati/versiuni de contract, concedii, prezente si cheltuieli ale angajatilor.
- Delegații interne/externe, durata, valuta si curs documentat, avans, decont, restituire,
  delimitarea diurnei impozabile/neimpozabile pentru scenariul simplificat.
- Pontaj lunar verificat, preluarea concediilor aprobate cu clasificare explicita,
  indemnizatie CO introdusa dupa verificare, prime si ore suplimentare.
- Calcul standard DEMO: CAS, CASS, impozit, CAM; rotunjire HALF_UP la leu pentru retineri.
- Diurna impozabila deja decontata intra in baza de calcul, dar nu se plateste a doua oara.
- State/fluturasi, contabilizare, plati simulate, reconcilierea 421/4281/542.
- Documente QWeb HTML imprimabile in browser, fara dependenta de wkhtmltopdf.
- Excel cu patru foi: stat, pontaj, diurne si pregatire D112.

## Date fictive si rezultate

Octombrie 2026, 22 zile lucratoare, trei angajati: Ion, Mara, Radu. Datele nu contin CNP,
email sau IBAN real. Contracte cu salarii de baza 11000, 13200 si 8800 RON.
Doua cereri de concediu aprobate: 2 zile CO si 1 zi fara plata. Sase inregistrari de prezenta
sunt exemple punctuale; nu reprezinta intregul pontaj lunar si nu se extrapoleaza automat.

| Salariat | Brut salarial | Diurna impozabila | CAS | CASS | Impozit | CAM | Net salariu |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ion | 11000 | 52.50 | 2763 | 1105 | 718 | 249 | 6414 |
| Mara | 14225 | 218.75 | 3611 | 1444 | 939 | 325 | 8231 |
| Radu | 8400 | 0 | 2100 | 840 | 546 | 189 | 4914 |

Net total 19559 RON, CAM 763 RON, cost salarial 34388 RON. Deconturi separate 5075 RON:
975, 3950 si 150 RON. Ultimul exemplu restituie 50 RON din avansul de 200 RON.
Cursul EUR/RON=5 este fictiv. Parametrii de diurna sunt exemple, nu cotatii sau politici aprobate.
Octombrie este contabilizat/achitat; noiembrie are trei ciorne pentru exercitii, fara postari.
Inchiderea anterioara a veniturilor/cheltuielilor nu a fost repetata; noile cheltuieli se vad in rapoarte.

## Limita fiscala explicita

Acesta NU este un motor complet de salarizare pentru productie. Calculele sunt blocate in alta baza.
Scenariul este limitat la norma de 8h/40h, contract ce acopera luna, conditii normale si brut salarial
de minimum 8000 RON. Nu implementeaza calculul pentru salariul minim/facilitati, timp partial,
tichete, concedii medicale, conditii speciale sau incetare/angajare in cursul lunii.
CO foloseste o indemnizatie zilnica introdusa si verificata, nu calculeaza automat media legala.
Deducerile sunt introduse dupa verificare, nu calculate din dependenti/varsta.
Deplasarile trebuie impartite la limita lunilor/tarilor; luna fiscala si cursul se verifica explicit.
Nu se deduce TVA din documentele de transport/cazare ale acestui scenariu.

**D112: numai pregatire/centralizator. Nu exista generator XML, validare XSD/DUK, semnare sau depunere.**
Butonul de verificare arata explicit aceste lipsuri. Nu produce un fisier XML cu format inventat.
Nu au fost cumparate/instalate module comerciale si nu exista integrare automata cu SAGA.

Surse consultate la 19.10.2026:

- ANAF, versiuni D112, inclusiv schema aplicabila din iulie 2026: https://static.anaf.ro/static/10/Anaf/Declaratii_R/112.html
- ANAF, Cod fiscal consolidat, articolele privind salariile/diurnele: https://static.anaf.ro/static/10/Anaf/legislatie/Cod_fiscal_norme_2023.htm
- HG 714/2018 actualizata, diurna interna si prag de 12h: https://legislatie.just.ro/Public/DetaliiDocumentAfis/265878
- Odoo 19, localizari salarizare: https://www.odoo.com/documentation/19.0/applications/hr/payroll/payroll_localizations.html

## Protectii si verificare

- Acces numai grupului dedicat, reguli multi-companie; test cu utilizator intern fara acces.
- Datele aprobate/contabilizate nu se modifica direct; parametrii folositi se pastreaza.
- Blocari la plati duplicate, sold/contract/pontaj invalid, concediu medical si conturi neconfigurate.
- Blocare pe rand in actiunile de plata; note native echilibrate si reconciliate.
- Nicio trimitere externa, coada email goala, sarcini programate dezactivate.

Scripturi tehnice, fara lansatoare noi:

- `scripts/hr_payroll_seed.py`: scenariul fictiv idempotent, nu se ruleaza peste modificari manuale fara revizuire.
- `scripts/hr_payroll_verify.py`: 83 verificari HTTP/contabile/rapoarte in starea livrata.
- `scripts/hr_payroll_transaction_tests.py`: Odoo shell, teste cu rollback pentru calcul/postare/plata,
  cazuri invalide, limite 12h/24h, imutabilitate si drepturi.
- `scripts/financial_audit_demo_reports.py`: rapoarte financiare reconciliate cu registrul curent.

Rezultate: `logs/hr-payroll-verification.json`, `logs/hr-payroll-transaction-tests.json`.
Exporturi: `logs/hr-payroll-exports/`. Nu s-a facut inspectie vizuala a browserului.
Backup inainte de instalare: `logs/backups/greentech-financiar-test-20261019-133707.zip`.

# Import SAGA pentru Odoo 19

Modul pentru importul inițial al unui backup SAGA Firebird 3 (`.fdb`, ODS 12), într-o firmă nouă din aceeași aplicație Odoo. Nu folosește Docker.

## Utilizare

Financiar → Import SAGA → Importă backup .fdb → Nou.

1. Completează denumirea, CUI-ul, numărul de înregistrare și adresa firmei. Aceste metadate nu sunt toate disponibile în fișierul SAGA.
2. Încarcă backupul și confirmă că este o copie consistentă.
3. Apasă **Analizează backupul**. Nu se creează contabilitate în acest pas.
4. Dacă verificările trec, apasă **Importă firma**. Operația durează aproximativ un minut pentru backupul verificat.
5. Selectează firma din selectorul Odoo de companii. Documentele se găsesc în **Documente SAGA**, iar facturile obișnuite și în ecranele native Facturi clienți / Facturi furnizori.

Importul este disponibil administratorilor. Contabilii autorizați pentru firma respectivă pot vedea documentele, registrul și imobilizările. Istoricul salarial cere drepturi HR; arhiva detaliată și backupul sunt accesibile administratorilor.

## Profil verificat

Verificat efectiv cu backupul DARIUSMED confirmat de utilizator: 209 tabele, 4.778 de rânduri, 17 furnizori, 4 clienți, 111 documente, 453 note contabile, 10 imobilizări, un salariat și 18 antete de state salariale. Cele 860 de rânduri SAGA includ formule compuse; `%` și laturile goale se interpretează ca structură de formulă, nu ca niște conturi suplimentare.

- 88 de facturi native Odoo, cu liniile și conturile efectiv contabilizate în SAGA. Numerele originale rămân în referință și în documentele SAGA; numerele tehnice Odoo au propria secvență.
- 21 de încasări directe în casă și două documente de intrare cu debit/credit pe același cont rămân documente istorice legate de nota originală. Nu li se inventează creanțe sau datorii.
- Plățile se păstrează în registrul contabil și se reconciliază cu facturile folosind legăturile SAGA. Supraplățile rămân pe pozițiile de plată ale partenerilor; nu se transformă în solduri negative artificiale ale facturilor Odoo. Nu se execută transferuri bancare.
- Registrul complet include soldurile inițiale, închiderile, amortizarea și salariile. Nu se postează aceste sume de două ori.
- Registrul imobilizărilor și antetele salariale sunt **istorice**, nu planuri noi de amortizare sau state recalculate. Tabelul SS al backupului verificat este gol: nu există bază pentru inventarea fluturașilor individuali. Nu se generează declarații fiscale ori depuneri ANAF.
- Arhiva păstrează toate rândurile, cu mascarea câmpurilor tehnice de parolă/token. Backupul original este păstrat separat ca atașament administrativ. PDF/XML/recipise stocate în afara bazei nu pot fi reconstruite din acest fișier.

## Verificări și limite

Citirea folosește o copie temporară, tranzacție read-only, database triggers dezactivate și verificarea COUNT(*) pentru fiecare tabel. Importul folosește ORM Odoo, cu anulare integrală a noii firme și a documentelor la eroare. Se compară debitul/creditul pe fiecare cont și an, totalurile și soldurile facturilor. Se verifică separat păstrarea documentelor GreenTech DEMO.

Nu este un convertor universal pentru orice variantă SAGA. Profilul operațional actual acceptă schema verificată, operațiuni în RON fără TVA pe documente. TVA, valută, stocuri și detalii salariale/diurne suplimentare produc un blocaj explicit până la implementarea și verificarea mapării lor; nu sunt ignorate în tăcere.

Reimportul aceluiași backup este blocat. Importul altui backup pentru un CUI deja existent este blocat: actualizarea incrementală și rezolvarea conflictelor sunt un flux separat, neimplementat. Importul inițial nu șterge și nu înlocuiește firme existente.

## Cerințe

- Windows: componentele existente `C:\SAGA C.3.0\FirebirdSql.Data.FirebirdClient.dll` și `C:\Program Files\Firebird\Firebird30_Saga\fbclient.dll`; PowerShell pentru cititorul separat.
- Linux: Python `fdb==2.0.4`, `libfbclient2`, motorul embedded din `firebird3.0-server-core`. Instalatorul configurează un runtime privat în `/opt/greentech-financiar/saga-firebird`, fără serviciu Firebird public. Cititorul este verificat cu o bază sintetică înainte de actualizarea Odoo. Execuția Linux trebuie confirmată pe server; dezvoltarea și importul complet au fost verificate pe Windows.
- Limite interactive: 256 MB pentru FDB și 250.000 rânduri. Nginx-ul existent are limita 64 MB pentru cerere; backupul de 43,8 MB verificat încape după codarea base64. Backupurile mai mari cer ajustarea controlată a limitei sau un flux de import pe loturi.

## Teste

`scripts/test_saga_core.py`: 13 verificări, inclusiv diferență de un ban, formulă compusă incompletă, sold neexplicat, dubluri și date nesuportate.

`scripts/saga_test_odoo.py`: încărcare FDB, analiză, import complet, vizualizări, repetarea fără dubluri și păstrarea firmei DEMO într-o bază de verificare.

`scripts/saga_test_security.py`: 11 verificări de acces, izolare, duplicate și comparație SQL independentă debit/credit.

Importul local a fost verificat și prin HTTP/RPC pe portul 8070. Inspecția vizuală într-un browser nu a fost disponibilă în sesiunea de lucru.
# Lucru curent după import

În importul finalizat sau la analiza unui backup deja importat, butoanele Clienți,
Furnizori, Facturi, Casă și bănci, Fișe parteneri și Angajați selectează automat
firma și deschid înregistrările native. Meniul Import SAGA → Lucru curent folosește
firma activă; permite și documente noi, nu filtrează numai istoricul importat.

Jurnalele de bancă și casă folosesc conturile cu operațiuni reale din SAGA.
Plățile bancare au conturi de decontare pentru reconcilierea extrasului; plățile
în numerar folosesc direct contul casei. Jurnalul bancar generic BNK1 este arhivat
numai dacă este complet nefolosit și nu are un cont bancar configurat.
Actualizarea nu generează note contabile și nu reimportă documentele.

Registru casă/bancă și Fișe parteneri afișează înregistrările validate, grupate
pe cont/partener; lista poate fi filtrată și exportată prin funcția Odoo Export.
Soldul net reprezintă debit minus credit. Pentru extrase bancare NOI, completează
soldul inițial conform băncii, verificat cu registrul contabil, și introdu numai
operațiunile care nu sunt deja contabilizate în istoricul SAGA. Extrasele originale
nu sunt fabricate din notele contabile. Încasările/plățile în curs se reconciliază
cu tranzacțiile extrasului, nu se înregistrează încă o dată pe venituri/cheltuieli.

Verificare pe copia izolată: factură nouă către client importat, validare,
încasare, extras cu sold inițial, reconciliere până la starea paid; factură nouă
de la furnizor importat. Toate documentele de verificare sunt anulate prin rollback.
Imobilizările și antetele salariale rămân istorice, conform limitelor de mai jos.


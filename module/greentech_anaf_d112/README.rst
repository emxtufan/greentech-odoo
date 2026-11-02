ANAF — Declarația 112
====================

Modul Odoo 19 pentru dosare D112, separat de salarizarea demonstrativă.
Nu reprezintă un motor complet de salarizare și nu este certificat fiscal.

Utilizare
---------

1. Deschideți ANAF > Declarația 112 > Nou(ă). Selectați firma și perioada.
2. Importați XML-ul generat în SAGA pentru aceeași firmă și perioadă.
   Alternativ, „Preia date firmă” completează numai identificarea angajatorului.
3. Verificați Plătitor, Asigurați, Perioadă și semnatar. Secțiunile A și B
   pentru asigurați reprezintă alternative în schema ANAF.
4. „Verifică structură” verifică XSD, firma, perioada și unicitatea CNP.
   Aceasta NU verifică toate calculele fiscale.
5. „Validează ANAF” rulează distribuția locală DUKIntegrator prin Java.
   Numai confirmarea explicită a programului acordă starea „Validat DUKIntegrator”.
6. Generarea PDF este permisă după această validare. XML-ul încorporat trebuie
   să coincidă cu declarația validată. PDF-ul rezultat este nesemnat.
7. Semnarea, depunerea și verificarea acceptării se efectuează separat.
   Indexul și recipisa pot fi arhivate manual în dosar.

Orice modificare a conținutului, perioadei sau firmei șterge rezultatele
validării și fișierele generate anterior. Dosarele cu index/recipisă necesită
o revizie pentru schimbarea conținutului.

Profil și limite
---------------

* Schema ANAF: D112_A7.2.6-v7-07/2026-structura-140826.
* Perioade acceptate explicit de versiunea instalată: iulie–octombrie 2026.
  O altă perioadă necesită verificarea și includerea profilului aferent.
* Importul/exportul păstrează secțiunile, ordinea și valorile XML; datele
  necunoscute sunt respinse, nu eliminate în tăcere.
* Nu există recalculare automată din salariile istorice SAGA sau din modulul
  demonstrativ. CAS, CASS, CAM, deducerile și concediile trebuie fundamentate
  prin datele salariale aferente firmei și perioadei.
* Java nu era disponibil la instalarea din 20.10.2026. Integrarea DUK și
  generarea PDF sunt implementate, dar execuția reală și o declarație fiscală
  de referință NU au fost validate. Nu există confirmare de acceptare ANAF.

Configurare
-----------

Administratorul are acces la ANAF > Configurare. Distribuția ANAF locală
este în tools/anaf/duk; runtime-lock.json identifică prin SHA-256 cele nouă
JAR-uri copiate din distribuția ANAF deja prezentă lângă SAGA.
Nu s-a copiat codul aplicației SAGA și nu s-a modificat instalarea SAGA.

Configurați calea către java.exe dintr-un runtime compatibil cu distribuția
ANAF. Hash-urile locale identifică fișierele; nu confirmă actualitatea fiscală.
După actualizarea distribuției, verificați versiunea și compatibilitatea
înainte de regenerarea manifestului. Nu actualizați automat manifestul în
timpul validării.

Grupul „ANAF — Declarația 112” acordă acces la dosare. Regula multi-companie
limitează citirea și modificarea la firmele autorizate. Doar administratorul
configurează executabilul și directorul validatorului.

Verificări
----------

* scripts/d112_unit_tests.py: 16 teste XML, import/export, integritate și
  comportament la lipsa confirmării validatorului.
* tests/test_declaration.py: 8 teste Odoo, inclusiv acces, multi-companie,
  import, revizii, invalidarea rezultatelor și imposibilitatea falsificării
  stării prin RPC. Testele de stare folosesc explicit un validator simulat.
* scripts/d112_browser_test.mjs: interfața reală Chromium pe o copie a
  bazei, editare rapidă cu întârziere artificială a răspunsurilor, salvare,
  ordine secțiuni, verificare XSD și configurare.
* Aceste teste confirmă comportamentul software, nu corectitudinea unei
  declarații reale sau echivalența completă cu SAGA.

Surse
-----

* https://static.anaf.ro/static/10/Anaf/Declaratii_R/112.html
* https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/d112_0726_140826.xsd
* https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/structura_D112_0726_070926.pdf
* https://manual.sagasoft.ro/sagaps/topic-42-state-salarii.html

Identificarea surselor locale și a schemei se află în schemas/sources.json.
Etichetele suplimentare provin din formularul oficial D112 instalat local,
actualizat la 07.09.2026; etichetele ambigue nu sunt preluate.

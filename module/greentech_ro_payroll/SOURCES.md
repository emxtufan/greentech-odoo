# Profil salarial implementat

Generare nativă din `hr.employee` / `hr.version`, fără dependență de SAGA.
Perioade 07–10/2026; CIM normal, rezident major, nepensionar, normă 8/40,
lună complet lucrată, prime salariale, deduceri personale și facilitatea
de 200 lei când condițiile sunt confirmate.

Surse oficiale consultate la 20.10.2026:

- https://static.anaf.ro/static/10/Anaf/Declaratii_R/112.html
- https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/structura_D112_0726_070926.pdf
- https://legislatie.just.ro/Public/DetaliiDocument/308231 — HG 146/2026, minim 4.325 lei de la 1 iulie.
- https://legislatie.just.ro/Public/DetaliiDocument/305817 — OUG 89/2025, art. III, 200 lei pentru semestrul II, condiții și plafon 4.600 lei.
- https://legislatie.just.ro/Public/DetaliiDocument/262588 — OG 16/2022, tabel art.77, deduceri personale.
- https://static.anaf.ro/static/10/Anaf/legislatie/Cod_fiscal_norme_2023.htm — Cod fiscal consolidat, art.77,78,138,156,220^3.

Limite vizibile în interfață și impuse de motor: nu sunt implementate concedii
(inclusiv CO/CM), suspendări, angajare/încetare/modificare contract în cursul
lunii, timp parțial, pensionari, tichete, diurne, ore suplimentare, scutiri,
alte deduceri, condiții speciale, venituri nesalariale, sedii secundare,
raportare trimestrială sau rectificări după depunere.
Nu se creează note contabile, plăți, semnături ori depuneri.

## Neconcordanțe ale XSD-ului publicat

Originalul furnizat de utilizator: `d112_0726_140826 (1).xsd`.
SHA256: `9603d3aa1b0bd7b56f91584e41ecdc3a09dda3abf724631f42f27c24b9b45788`.

`A_sal1`, `A_sal2` și `A_1` folosesc în original `IntInt1_30SType`:
interval 1–30. Anexa descrie salariile ca N(15) și include tipul 51.
Originalul nu este modificat. Sumele reale nu sunt ajustate artificial
pentru a trece XSD. Raportul strict XSD rămâne vizibil.

Calculele și generarea unui XML de lucru NU constituie certificare fiscală.
Starea „Validat DUKIntegrator” poate proveni numai dintr-o execuție
reușită a validatorului oficial, pentru exact XML-ul curent.

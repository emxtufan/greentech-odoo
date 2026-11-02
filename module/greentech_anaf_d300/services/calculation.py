"""OPANAF 174/2026: visible row numbers are NOT the historical XML keys.

Sources: official form/instructions D300_OPANAF_174_2026.pdf; structure v12;
the ANAF D300_A12 PDF's XML bindings. No SAGA data or program dependency.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from lxml import etree

NS = "mfp:anaf:dgti:d300:declaratie:v12"
SOURCE = "https://static.anaf.ro/static/10/Anaf/Declaratii_R/300.html"
# number, short explanation, base XML key, tax XML key, parent subtotal
ROWS = [
 ("1", "Livrări intracomunitare de bunuri", "R1_1", "", ""),
 ("2", "Regularizări livrări intracomunitare", "R2_1", "", ""),
 ("3", "Operațiuni cu locul în afara României", "R3_1", "", ""),
 ("3.1", "Servicii intracomunitare", "R3_1_1", "", "3"),
 ("4", "Regularizări servicii intracomunitare", "R4_1", "", ""),
 ("5", "Achiziții intracomunitare bunuri — colectată", "R5_1", "R5_2", ""),
 ("5.1", "Furnizor înregistrat TVA în statul de livrare", "R5_1_1", "R5_1_2", "5"),
 ("6", "Regularizări AIC bunuri — colectată", "R6_1", "R6_2", ""),
 ("7", "Alte achiziții cu taxare inversă — colectată", "R7_1", "R7_2", ""),
 ("7.1", "Servicii intracomunitare — colectată", "R7_1_1", "R7_1_2", "7"),
 ("8", "Regularizări servicii IC — colectată", "R8_1", "R8_2", ""),
 ("9", "Livrări și servicii 21%", "R9_1", "R9_2", ""),
 ("10", "Livrări și servicii 11%", "R10_1", "R10_2", ""),
 ("11", "Livrări 9% art. III Legea 141/2025", "R11_1", "R11_2", ""),
 ("12", "Taxare inversă internă — colectată", "R12_1", "R12_2", ""),
 ("12.1", "Taxare inversă internă 21% — colectată", "R12_1_1", "R12_1_2", "12"),
 ("12.2", "Taxare inversă internă 11% — colectată", "R12_2_1", "R12_2_2", "12"),
 ("13", "Livrări cu taxare inversă", "R13_1", "", ""),
 ("14", "Scutiri cu drept de deducere / exporturi", "R14_1", "", ""),
 ("15", "Scutiri fără drept de deducere", "R15_1", "", ""),
 ("16", "Regularizări taxă colectată", "R16_1", "R16_2", ""),
 ("17", "Vânzări la distanță / servicii electronice, locul în RO", "R64_1", "R64_2", ""),
 ("18", "Regularizări operațiuni de la rândul 17", "R65_1", "R65_2", ""),
 ("19", "TOTAL TAXĂ COLECTATĂ", "R17_1", "R17_2", ""),
 ("20", "Achiziții intracomunitare bunuri — deductibilă", "R18_1", "R18_2", ""),
 ("20.1", "Furnizor înregistrat TVA în statul de livrare", "R18_1_1", "R18_1_2", "20"),
 ("21", "Regularizări AIC bunuri — deductibilă", "R19_1", "R19_2", ""),
 ("22", "Alte achiziții cu taxare inversă — deductibilă", "R20_1", "R20_2", ""),
 ("22.1", "Servicii intracomunitare — deductibilă", "R20_1_1", "R20_1_2", "22"),
 ("23", "Regularizări servicii IC — deductibilă", "R21_1", "R21_2", ""),
 ("24", "Achiziții și importuri 21%", "R22_1", "R22_2", ""),
 ("25", "Achiziții și importuri 11%", "R23_1", "R23_2", ""),
 ("26", "Taxare inversă internă — deductibilă", "R25_1", "R25_2", ""),
 ("26.1", "Taxare inversă internă 21% — deductibilă", "R25_1_1", "R25_1_2", "26"),
 ("26.2", "Taxare inversă internă 11% — deductibilă", "R25_2_1", "R25_2_2", "26"),
 ("27", "Compensație forfetară agricultori", "", "R43_2", ""),
 ("28", "Regularizări compensație forfetară", "", "R44_2", ""),
 ("29", "Achiziții scutite sau neimpozabile", "R26_1", "", ""),
 ("29.1", "Servicii intracomunitare scutite", "R26_1_1", "", "29"),
 ("30", "TOTAL TAXĂ DEDUCTIBILĂ", "R27_1", "R27_2", ""),
 ("31", "SUBTOTAL TAXĂ EFECTIV DEDUSĂ", "", "R28_2", ""),
 ("32", "TVA restituită cumpărătorilor străini", "", "R29_2", ""),
 ("33", "Regularizări taxă dedusă", "R30_1", "R30_2", ""),
 ("34", "Ajustări pro-rata / ajustări de taxă", "", "R31_2", ""),
 ("35", "TOTAL TAXĂ DEDUSĂ", "", "R32_2", ""),
 ("36", "TVA negativă în perioada curentă", "", "R33_2", ""),
 ("37", "TVA de plată în perioada curentă", "", "R34_2", ""),
 ("38", "TVA precedentă de plată, rămasă neachitată", "", "R35_2", ""),
 ("39", "Diferențe de plată stabilite prin decizie", "", "R36_2", ""),
 ("40", "TVA DE PLATĂ CUMULAT", "", "R37_2", ""),
 ("41", "TVA negativă reportată, nesolicitată la rambursare", "", "R38_2", ""),
 ("42", "Diferențe negative stabilite prin decizie", "", "R39_2", ""),
 ("43", "TVA NEGATIVĂ CUMULATĂ", "", "R40_2", ""),
 ("44", "SOLD TVA DE PLATĂ", "", "R41_2", ""),
 ("45", "SOLD TVA NEGATIVĂ", "", "R42_2", ""),
]
BY_ROW = {r[0]: r for r in ROWS}
CALCULATED = {"19", "30", "31", "35", "36", "37", "40", "43", "44", "45"}
INPUT_ROWS = [(r[0], r[0] + " · " + r[1]) for r in ROWS if r[0] not in CALCULATED]
SALE_ROWS = [r for r in INPUT_ROWS if float(r[0]) < 19]
BUY_ROWS = [r for r in INPUT_ROWS if 20 <= float(r[0]) <= 34]
INFO = {
 "nr_facturi": "Facturi emise după inspecția fiscală — număr",
 "baza": "Facturi emise după inspecția fiscală — bază",
 "tva": "Facturi emise după inspecția fiscală — TVA",
 "nr_facturi_primite": "Facturi primite după inspecția fiscală — număr",
 "baza_primite": "Facturi primite după inspecția fiscală — bază",
 "tva_primite": "Facturi primite după inspecția fiscală — TVA",
 "nr_fact_emise": "Facturi după reînregistrare TVA — număr",
 "total_baza": "Facturi după reînregistrare TVA — bază",
 "total_tva": "Facturi după reînregistrare TVA — TVA",
 "valoare_a": "TVA la încasare: bază neexigibilă în sold",
 "tva_a": "TVA la încasare: TVA neexigibilă în sold",
 "valoare_a1": "Din care ultimele 6 luni: bază vânzări",
 "tva_a1": "Din care ultimele 6 luni: TVA vânzări",
 "valoare_b": "TVA la plată: bază în sold",
 "tva_b": "TVA la plată: TVA în sold",
 "valoare_b1": "Din care ultimele 6 luni: bază achiziții",
 "tva_b1": "Din care ultimele 6 luni: TVA achiziții",
 "total_precedent": "Operațiuni art. 278¹: total an precedent",
 "total_curent": "Operațiuni art. 278¹: total an curent",
}

def lei(value):
    return int(Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()

def period(year, month, kind):
    if year != 2026:
        raise ValueError("Profilul instalat este OPANAF 174/2026, pentru anul 2026.")
    if not 1 <= month <= 12:
        raise ValueError("Luna trebuie să fie între 1 și 12.")
    if kind == "L":
        start = month
    elif kind == "T" and month in (2, 3, 5, 6, 8, 9, 11, 12):
        start = ((month - 1) // 3) * 3 + 1
    elif kind == "S" and month in (6, 12):
        start = month - 5
    elif kind == "A" and month == 12:
        start = 1
    else:
        raise ValueError("Luna de final nu corespunde perioadei fiscale.")
    return date(year, start, 1), date(year, month, monthrange(year, month)[1])

def calculate(contributions, adjustments, prorata, info=None):
    """Round declared leaf totals once; then sum declared integers, never floats.

    A contribution on a 'din care' row propagates to its parent exactly once.
    Eligible input tax is independent of gross tax; pro-rata applies only to
    explicitly designated mixed-use purchases, never all purchases.
    """
    values = {r[0]: {"base": Decimal(0), "tax": Decimal(0)} for r in ROWS}
    deducted = Decimal(0)
    def add(code, base, tax):
        if code not in BY_ROW or code in CALCULATED:
            raise ValueError("Rând de intrare nepermis: " + code)
        definition = BY_ROW[code]
        if base and not definition[2] or tax and not definition[3]:
            raise ValueError("Coloană inexistentă la rândul " + code)
        values[code]["base"] += Decimal(str(base or 0))
        values[code]["tax"] += Decimal(str(tax or 0))
        if definition[4]:
            add(definition[4], base, tax)
    for item in contributions:
        code = item["row"]
        add(code, item["base"], item["tax"])
        if 20 <= float(code) <= 28:
            factor = Decimal(str(prorata)) / 100 if item.get("prorata") else Decimal(1)
            deducted += Decimal(str(item.get("eligible", item["tax"]))) * factor
    for adj in adjustments:
        add(adj["row"], adj["base"], adj["tax"])
        if 20 <= float(adj["row"]) <= 28:
            deducted += Decimal(str(adj["eligible"]))
    result = {code: {k: lei(v) for k, v in amounts.items()} for code, amounts in values.items()}
    def total(target, codes, columns=("base", "tax")):
        for column in columns:
            result[target][column] = sum(result[c][column] for c in codes)
    total("19", [str(n) for n in range(1, 19)])
    total("30", [str(n) for n in range(20, 29)])
    result["31"]["tax"] = lei(deducted)
    total("35", ["31", "32", "33", "34"], ("tax",))
    result["36"]["tax"] = max(result["35"]["tax"] - result["19"]["tax"], 0)
    result["37"]["tax"] = max(result["19"]["tax"] - result["35"]["tax"], 0)
    total("40", ["37", "38", "39"], ("tax",))
    total("43", ["36", "41", "42"], ("tax",))
    result["44"]["tax"] = max(result["40"]["tax"] - result["43"]["tax"], 0)
    result["45"]["tax"] = max(result["43"]["tax"] - result["40"]["tax"], 0)
    attrs = {}
    for code, label, basekey, taxkey, parent in ROWS:
        if basekey:
            attrs[basekey] = result[code]["base"]
        if taxkey:
            attrs[taxkey] = result[code]["tax"]
    attrs.update({key: lei((info or {}).get(key, 0)) for key in INFO})
    # ANAF PDF sum control: all numeric declaration cells (including 'din care'
    # and totals), excluding ancillary information after the main VAT balance.
    attrs["totalPlata_A"] = sum(v for k, v in attrs.items() if k.startswith("R") or k in (
        "nr_facturi", "baza", "tva", "nr_facturi_primite", "baza_primite", "tva_primite"))
    return result, attrs

def payment_reference(year, month, kind):
    # Encoding used by ANAF soft A (nominal 25th; not a due-date calendar).
    due = date(year + (month == 12), month % 12 + 1, 25)
    prefix = "10" + {"L": "301", "T": "302", "S": "303", "A": "304"}[kind]
    prefix += f"01{month:02d}{year % 100:02d}{due:%d%m%y}0000"
    return prefix + f"{sum(map(int, prefix)) % 100:02d}"

def xml_bytes(identity, attrs):
    root = etree.Element("{%s}declaratie300" % NS,
                         nsmap={None: NS, "xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    root.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", NS + " d300.xsd")
    for key, value in {**identity, **attrs}.items():
        if value is not None and value != "":
            root.set(key, str(value))
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)

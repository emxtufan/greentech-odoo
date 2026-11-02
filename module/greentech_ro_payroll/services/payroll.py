"""Native, deliberately bounded salary calculation; no SAGA dependency.

Profile: July-October 2026, resident employee, single full-time CIM, normal
conditions, whole month worked, no benefits/medical leave/special tax regimes.
Official sources and known XSD defects: ../SOURCES.md.
DUK validation is a separate operation and is never inferred from these totals.
"""
import calendar
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import hashlib
import json
import re

MINIMUM = Decimal("4325")
PROFILE = "RO-CIM-normal-2026H2-v1"


def integer(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def month_dates(year, month):
    month = int(month)
    if year != 2026 or month not in (7, 8, 9, 10):
        raise ValueError("Profilul salarial verificat documentar acoperă 07–10/2026.")
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def working_days(year, month):
    start, end = month_dates(year, month)
    # Only the bounded July-October 2026 profile. August 15 falls on Saturday.
    return sum(date(year, int(month), day).weekday() < 5
               and (int(month), day) != (8, 15) for day in range(1, end.day + 1))


def cnp_birth(cnp):
    if not re.fullmatch(r"[1-6]\d{12}", cnp or ""):
        raise ValueError("CNP: profilul curent acceptă CNP românesc, 13 cifre, cu prima cifră 1–6.")
    check = sum(int(a) * int(b) for a, b in zip(cnp[:12], "279146358279")) % 11
    if int(cnp[-1]) != (1 if check == 10 else check):
        raise ValueError("CNP: cifra de control este incorectă.")
    try:
        birth = date({1: 1900, 2: 1900, 3: 1800, 4: 1800, 5: 2000, 6: 2000}[int(cnp[0])]
                     + int(cnp[1:3]), int(cnp[3:5]), int(cnp[5:7]))
    except ValueError:
        raise ValueError("CNP: data nașterii este incorectă.") from None
    if not (1 <= int(cnp[7:9]) <= 46 or int(cnp[7:9]) in (51, 52)) or int(cnp[9:12]) == 0:
        raise ValueError("CNP: județul sau numărul de ordine este incorect.")
    return birth


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def calculate(data):
    start, end = month_dates(data["year"], data["month"])
    if not data.get("confirmed"):
        raise ValueError("Confirmați pontajul și încadrarea fiscală pentru această lună.")
    if data.get("profile") != "normal":
        raise ValueError("Alegeți profilul CIM normal numai dacă situația salariatului corespunde.")
    birth = cnp_birth(data.get("cnp", ""))
    eighteenth = date(birth.year + 18, birth.month, min(birth.day, calendar.monthrange(birth.year + 18, birth.month)[1]))
    if start < eighteenth:
        raise ValueError("Profilul curent acoperă salariați majori.")
    if str(birth) != str(data.get("birthday")):
        raise ValueError("Data nașterii din fișa salariatului diferă de CNP.")
    if not data.get("last_name") or not data.get("first_name") or not data.get("house"):
        raise ValueError("Completați numele, prenumele și casa de sănătate în profilul ANAF al angajatului.")
    if data.get("role") not in ("primary", "secondary"):
        raise ValueError("Precizați dacă aici este funcția de bază.")
    if not data.get("start") or str(data["start"]) > str(start) or (
            data.get("end") and str(data["end"]) < str(end)):
        raise ValueError("Contractul trebuie să acopere luna completă. Angajările/încetările în cursul lunii necesită alt profil.")
    if data.get("version_changes") or data.get("hours_week") != 40 or data.get("hours_day") != 8 or not data.get("standard_calendar"):
        raise ValueError("Profilul curent cere un singur contract, fără modificări în lună, 8 ore/zi și 40 ore/săptămână.")
    if data.get("leave_count"):
        raise ValueError("Există concedii/absențe în Odoo în această lună. Calculul lunilor cu concedii nu este încă implementat.")
    days = working_days(data["year"], data["month"])
    if data.get("worked_days") != days:
        raise ValueError(f"Acest profil acoperă luna integral lucrată ({days} zile). Absențele și suspendările necesită alt profil.")
    wage, bonus = Decimal(str(data["wage"])), Decimal(str(data.get("bonus", 0)))
    if not wage.is_finite() or not bonus.is_finite() or wage < MINIMUM or bonus < 0:
        raise ValueError("Salariul contractual trebuie să fie cel puțin 4.325 lei; primele nu pot fi negative.")
    if wage != wage.to_integral_value() or bonus != bonus.to_integral_value():
        raise ValueError("Acest profil cere salariu și prime exprimate în lei întregi.")
    dependents, children = data.get("dependents", 0), data.get("children", 0)
    if not isinstance(dependents, int) or not isinstance(children, int) or not 0 <= dependents <= 99 or not 0 <= children <= 20:
        raise ValueError("Verificați numărul persoanelor în întreținere și al copiilor eligibili.")
    primary = data["role"] == "primary"
    if not primary and (dependents or children):
        raise ValueError("Deducerile personale se acordă la funcția de bază.")
    gross = int(wage + bonus)
    exemption = 0
    if primary and wage == MINIMUM and gross <= 4600:
        if data.get("minimum_status") not in ("eligible", "reduced"):
            raise ValueError("Verificați condiția privind nereducerea salariului pentru facilitatea de 200 lei (OUG 89/2025).")
        if data["minimum_status"] == "eligible":
            exemption = 200
    base = gross - exemption
    cas, cass = integer(Decimal(base) * Decimal(".25")), integer(Decimal(base) * Decimal(".10"))
    personal = youth = child = 0
    if primary:
        if gross <= MINIMUM + 2000:
            steps = max(0, int(((Decimal(gross) - MINIMUM) / 50).to_integral_value(rounding=ROUND_CEILING)))
            rate = Decimal(("20", "25", "30", "35", "45")[min(dependents, 4)]) - Decimal(".5") * steps
            personal = integer(MINIMUM * max(Decimal(0), rate) / 100)
            # Birthday-month edge case requires explicit verified entitlement.
            turn26 = date(birth.year + 26, birth.month, min(birth.day, calendar.monthrange(birth.year + 26, birth.month)[1]))
            if start <= turn26 <= end:
                raise ValueError("Luna împlinirii vârstei de 26 ani necesită verificarea separată a deducerii.")
            if end < turn26:
                youth = integer(MINIMUM * Decimal(".15"))
        child = children * 100
    available = max(0, base - cas - cass)
    personal = min(personal, available)
    youth = min(youth, available - personal)
    child = min(child, available - personal - youth)
    deduction = personal + youth + child
    taxable = max(0, available - deduction)
    tax = integer(Decimal(taxable) * Decimal(".10"))
    return dict(gross=gross, exemption=exemption, base=base, cas=cas, cass=cass,
                personal=personal, youth=youth, child=child, deduction=deduction,
                taxable=taxable, tax=tax, net=gross - cas - cass - tax,
                insured_type=51 if exemption else 1, bonus=int(bonus), days=days)


def totals(results):
    result = {key: sum(row[key] for row in results)
              for key in ("gross", "base", "cas", "cass", "tax", "net", "exemption", "deduction")}
    result["cam"] = integer(Decimal(result["base"]) * Decimal(".0225"))
    result["due"] = result["cas"] + result["cass"] + result["tax"] + result["cam"]
    result["cost"] = result["gross"] + result["cam"]
    return result


def node(tag, **attrs):
    return {"tag": tag, "attrs": {k: str(v) for k, v in attrs.items() if v is not None and v is not False}, "children": []}


def declaration(company, year, month, people):
    """Build all applicable A/E1/E2/E3 and employer sections from calculated inputs."""
    from odoo.addons.greentech_anaf_d112.services import document
    result = document.new_document(year, month, company["attrs"])
    result["attrs"].update(nume_declar=company["last_name"], prenume_declar=company["first_name"],
                           functie_declar=company["position"])
    employer = result["children"][0]
    results = [p["result"] for p in people]
    total = totals(results)
    employer["attrs"].update(datCAM="1", totalPlata_A=str(total["due"]))
    employer["children"] = [
        node("angajatorA", A_codOblig=code, A_codBugetar=budget, A_datorat=amount,
             A_deductibil=0, A_scutit=0, A_plata=amount)
        for code, budget, amount in [
            (602, "5503XXXXXX", total["tax"]), (412, "5503XXXXXX", total["cas"]),
            (432, "5503XXXXXX", total["cass"]), (480, "20470300XX", total["cam"])]
    ]
    employer["children"] += [
        node("angajatorB", B_cnp=len(people), B_sanatate=len(people), B_pensie=len(people),
             B_sal=len(people), B_brutSalarii=total["base"]),
        node("angajatorC1", C1_11=total["gross"], C1_12=0, C1_13=0, C1_21=0, C1_22=0, C1_23=0,
             C1_31=0, C1_32=0, C1_33=0, C1_T1=total["gross"], C1_T2=0, C1_T3=0,
             C1_T=0, C1_5=0, C1_7=0),
        node("angajatorC4", C4_baza=total["base"], C4_ct=total["cam"]),
        node("angajatorF1", F1_suma=total["tax"], F1_suma_ded=0, F1_suma_scut=0, F1_deplata=total["tax"]),
    ]
    for person in people:
        d, r = person["input"], person["result"]
        insured = node("asigurat", idAsig=d["employee_id"], cnpAsig=d["cnp"], numeAsig=d["last_name"],
                       prenAsig=d["first_name"], dataAng=date.fromisoformat(str(d["start"])).strftime("%d.%m.%Y"),
                       casaSn=d["house"], asigCI=1, asigSO=1, Timp_E3=r["tax"])
        insured["children"].append(node(
            "asiguratA", A_1=r["insured_type"], A_sal1=int(d["wage"]), A_sal2=r["gross"],
            A_2=0, A_3="N", A_4=8, A_5=r["base"], A_6=r["days"] * 8, A_7=0,
            A_8=r["days"], A_9=r["base"], A_11=r["base"], A_12=r["cass"],
            A_13=r["base"], A_14=r["cas"], A_13P=0, A_14P=0, A_11P=0,
            A_12P=0, A_14D=0, A_12D=0, A_13S=r["exemption"],
            A_13C=r["gross"] if r["exemption"] else 0))
        if d["role"] == "primary":
            insured["children"].append(node(
                "asiguratE1", E1_1=r["gross"], E1_2=r["cas"] + r["cass"], E1_3=d["dependents"],
                E1_4=r["deduction"], E1_41=r["personal"], E1_42=r["youth"] + r["child"],
                E1_421=r["youth"], E1_422=r["child"], E1_5=0, E1_6=r["taxable"], E1_7=r["tax"]))
        else:
            insured["children"].append(node("asiguratE2", E2_1=r["gross"], E2_2=r["cas"] + r["cass"],
                                            E2_3=r["taxable"], E2_4=r["tax"]))
        insured["children"].append(node(
            "asiguratE3", E3_1="A", E3_2=r["insured_type"], E3_3=1 if d["role"] == "primary" else 2,
            E3_4="P", E3_8=r["gross"], E3_61=r["bonus"], E3_9=r["cas"] + r["cass"],
            E3_19=0, E3_11=d["dependents"], E3_12=r["deduction"],
            E3_121=r["personal"], E3_122=r["youth"] + r["child"],
            E3_1221=r["youth"], E3_1222=r["child"], E3_13=0, E3_14=r["taxable"],
            E3_15=r["tax"], E3_16=r["net"]))
        result["children"].append(insured)
    return document.normalize(result)

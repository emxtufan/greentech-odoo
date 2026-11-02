"""D112 document model. XML-schema validity is distinct from fiscal validation."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from lxml import etree

BASE = Path(__file__).resolve().parents[1]
XS = "{http://www.w3.org/2001/XMLSchema}"
NS = "mfp:anaf:dgti:declaratie_unica:declaratie:v7"
MAX_BYTES = 16 * 1024 * 1024
MAX_NODES = 100000
PROFILE = {
    "code": "2026-07",
    "first_period": 202607,
    "last_verified_period": 202610,
    "version": "D112_A7.2.6-v7-07/2026-structura-140826",
    "schema_url": "https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/d112_0726_140826.xsd",
    "rules_url": "https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/structura_D112_0726_070926.pdf",
    "index_url": "https://static.anaf.ro/static/10/Anaf/Declaratii_R/112.html",
}
TITLES = {
    "declaratieUnica": "Perioadă și semnatar", "angajator": "Plătitor / angajator",
    "angajatorA": "A. Creanțe fiscale", "angajatorB": "B. Indicatori angajator",
    "angajatorC1": "C.1. Condiții de muncă", "angajatorC2": "C.2. Indemnizații de sănătate",
    "angajatorC3": "C.3. Indemnizații", "angajatorC4": "C.4", "angajatorC5": "C.5",
    "angajatorD": "D. Angajator", "angajatorE1": "E.1", "angajatorE2": "E.2",
    "angajatorE3": "E.3", "angajatorE4": "E.4", "angajatorF1": "F.1. Sediu principal",
    "angajatorF2": "F.2. Sedii secundare", "asigurat": "Asigurat — identificare",
    "det1": "Detașare", "asiguratA": "A. Contract standard",
    "asiguratB1": "B.1. Contracte", "asiguratB2": "B.2. Condiții de muncă",
    "asiguratB3": "B.3. Concedii și indemnizații", "asiguratB4": "B.4. Totaluri",
    "asiguratC": "C. Alte categorii de asigurați", "asiguratD": "D. Concedii medicale",
    "asiguratE1": "E.1. Impozit", "asiguratE2": "E.2. Impozit",
    "asiguratE3": "E.3. Venituri și impozit", "asiguratE4": "E.4. Redistribuire impozit",
}
LABELS = {
    "luna_r": "Luna raportării", "an_r": "Anul raportării", "d_rec": "Rectificativă (0/1)",
    "tip_rec": "Tip rectificare", "nume_declar": "Nume semnatar", "prenume_declar": "Prenume semnatar",
    "functie_declar": "Funcția semnatarului", "cif": "CUI angajator", "cifS": "CUI succesor",
    "rgCom": "Registrul comerțului", "caen": "Cod CAEN", "den": "Denumire angajator",
    "adrSoc": "Adresă sediu social", "telSoc": "Telefon", "faxSoc": "Fax", "mailSoc": "Email",
    "adrFisc": "Adresă domiciliu fiscal", "telFisc": "Telefon fiscal", "faxFisc": "Fax fiscal",
    "mailFisc": "Email fiscal", "casaAng": "Casa de sănătate", "datCAM": "Datorează CAM (0/1)",
    "totalPlata_A": "Total de plată — secțiunea A", "A_codOblig": "Cod obligație",
    "A_codBugetar": "Cod bugetar", "A_datorat": "Datorat", "A_deductibil": "Deductibil",
    "A_scutit": "Scutit", "A_plata": "De plată", "B_cnp": "Număr asigurați",
    "B_sanatate": "Număr asigurați sănătate", "B_pensie": "Număr asigurați pensii",
    "B_sal": "Număr salariați", "B_brutSalarii": "Venit brut salarii",
    "cnpAsig": "CNP / NIF asigurat", "idAsig": "Identificator asigurat",
    "cisAsig": "Identificator asigurări", "numeAsig": "Nume", "prenAsig": "Prenume",
    "cnpAnt": "CNP anterior", "numeAnt": "Nume anterior", "prenAnt": "Prenume anterior",
    "dataAng": "Data începerii activității", "dataSf": "Data încetării activității",
    "casaSn": "Casa de sănătate asigurat", "asigCI": "Asigurat concedii și indemnizații",
    "asigSO": "Asigurat șomaj", "Timp_E3": "Total impozit E.3",
}


def parser():
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


@lru_cache(maxsize=1)
def schema_tree():
    return etree.parse(str(BASE / "schemas/d112_0726.xsd"), parser())


def period_check(year, month):
    try:
        period = int(year) * 100 + int(month)
        valid = 1 <= int(month) <= 12
    except (ValueError, TypeError):
        raise ValueError("Luna și anul trebuie să fie numere întregi.") from None
    if not valid or not PROFILE["first_period"] <= period <= PROFILE["last_verified_period"]:
        raise ValueError(
            "Profilul instalat acoperă 07–10/2026. Pentru altă perioadă trebuie instalată "
            "și verificată schema și versiunea validatorului aferente."
        )


@lru_cache(maxsize=1)
def editor_schema():
    root = schema_tree().getroot()
    simple = {e.get("name"): e for e in root.findall(XS + "simpleType")}
    groups = {e.get("name"): e for e in root.findall(XS + "group")}
    complex_types = {e.get("name"): e for e in root.findall(XS + "complexType")}
    labels_file = BASE / "schemas/labels.json"
    labels = json.loads(labels_file.read_text(encoding="utf-8")) if labels_file.exists() else {}
    definitions = {}

    def children(element, optional=False):
        items = []
        for child in element:
            opt = optional or child.get("minOccurs") == "0" or element.tag == XS + "choice"
            if child.tag == XS + "element":
                items.append({"tag": child.get("name"), "type": child.get("type"),
                              "min": 0 if opt else int(child.get("minOccurs", "1")),
                              "max": child.get("maxOccurs", "1")})
            elif child.tag == XS + "group":
                items.extend(children(groups[child.get("ref")], opt))
            elif child.tag in {XS + "sequence", XS + "choice", XS + "all", XS + "restriction", XS + "complexContent"}:
                items.extend(children(child, opt))
        return items

    def restrictions(name, seen=None):
        seen = set(seen or ())
        if name in seen or name not in simple:
            return {}
        seen.add(name)
        element = simple[name].find(XS + "restriction")
        if element is None:
            return {}
        result = restrictions(element.get("base"), seen)
        for key in ("enumeration", "pattern"):
            values = [x.get("value") for x in element.findall(XS + key)]
            if values:
                result[key] = values
        for key in ("minLength", "maxLength", "minInclusive", "maxInclusive"):
            part = element.find(XS + key)
            if part is not None:
                result[key] = part.get("value")
        return result

    for name, element in complex_types.items():
        attributes = []
        for attr in element.iter(XS + "attribute"):
            key = attr.get("name")
            attributes.append({
                "name": key, "label": LABELS.get(key) or labels.get(key) or key,
                "required": attr.get("use") == "required", "type": attr.get("type"),
                **restrictions(attr.get("type")),
            })
        definitions[name] = {"attributes": attributes, "children": children(element)}
    tags = {"declaratieUnica": "DeclaratieUnicaType"}
    for definition in definitions.values():
        tags.update({c["tag"]: c["type"] for c in definition["children"]})
    return {"profile": PROFILE, "types": definitions, "tags": tags, "titles": TITLES}


def empty_node(tag):
    spec = editor_schema()
    if tag not in spec["tags"]:
        raise ValueError("Secțiune D112 necunoscută.")
    definition = spec["types"][spec["tags"][tag]]
    return {
        "tag": tag, "attrs": {},
        "children": [empty_node(c["tag"]) for c in definition["children"] for _ in range(c["min"])],
    }


def new_document(year, month, company):
    period_check(year, month)
    node = empty_node("declaratieUnica")
    node["attrs"] = {"an_r": str(year), "luna_r": str(int(month)), "d_rec": "0"}
    employer = node["children"][0]
    employer["attrs"] = {k: str(v) for k, v in company.items() if v not in (False, None, "")}
    return node


def normalize(payload):
    schema = editor_schema()
    count = 0

    def visit(node, allowed, depth):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > 5 or not isinstance(node, dict):
            raise ValueError("Structura declarației este prea mare sau incorectă.")
        tag = node.get("tag")
        if tag not in allowed or tag not in schema["tags"]:
            raise ValueError(f"Secțiune necunoscută sau amplasată greșit: {tag!s}")
        definition = schema["types"][schema["tags"][tag]]
        attrs = node.get("attrs", {})
        if not isinstance(attrs, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in attrs.items()):
            raise ValueError("Valorile câmpurilor trebuie să fie texte; zero se introduce explicit.")
        names = {a["name"] for a in definition["attributes"]}
        if set(attrs) - names:
            raise ValueError(f"Câmpuri necunoscute în {tag}: {', '.join(sorted(set(attrs) - names))}")
        if any(len(v) > 20000 for v in attrs.values()):
            raise ValueError("Valoare prea lungă.")
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("Lista secțiunilor este incorectă.")
        allowed_children = {c["tag"] for c in definition["children"]}
        result = {"tag": tag, "attrs": {k: v for k, v in attrs.items() if v != ""},
                  "children": [visit(c, allowed_children, depth + 1) for c in children]}
        # Keep imported sequence (including repeating groups) exactly as provided.
        return result

    result = visit(payload, {"declaratieUnica"}, 0)
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("Declarația depășește limita de 16 MB.")
    return result


def to_xml(payload):
    data = normalize(payload)

    def build(node, top=False):
        element = etree.Element("{" + NS + "}" + node["tag"], nsmap={None: NS} if top else None)
        for key, value in node["attrs"].items():
            element.set(key, value)
        for child in node["children"]:
            element.append(build(child))
        return element

    return etree.tostring(build(data, True), encoding="UTF-8", xml_declaration=True, pretty_print=True)


def from_xml(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise ValueError("XML lipsă sau mai mare de 16 MB.")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD și entitățile XML externe nu sunt acceptate.")
    try:
        tree = etree.fromstring(raw, parser())
    except etree.XMLSyntaxError as exc:
        raise ValueError("XML incorect: " + str(exc)) from None
    if tree.getroottree().docinfo.doctype:
        raise ValueError("DTD nu este acceptat.")

    def node(element):
        if not isinstance(element.tag, str) or etree.QName(element).namespace != NS:
            raise ValueError("Namespace D112 incorect.")
        if element.text and element.text.strip():
            raise ValueError("D112 admite valori în atribute, nu text liber în secțiuni.")
        if any(child.tail and child.tail.strip() for child in element):
            raise ValueError("Text liber între secțiunile D112.")
        attrs = {k: v for k, v in element.attrib.items() if k != "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"}
        return {"tag": etree.QName(element).localname, "attrs": attrs,
                "children": [node(c) for c in element if isinstance(c.tag, str)]}

    result = normalize(node(tree))
    period_check(result["attrs"].get("an_r"), result["attrs"].get("luna_r"))
    return result


def validate(payload, company_vat, year, month):
    raw = to_xml(payload)
    root = etree.fromstring(raw, parser())
    issues = []
    try:
        period_check(year, month)
    except ValueError as exc:
        issues.append(str(exc))
    if root.get("an_r") != str(year) or root.get("luna_r") not in {str(int(month)), str(int(month)).zfill(2)}:
        issues.append("Perioada din document diferă de perioada dosarului.")
    employer = root.find("{" + NS + "}angajator")
    expected_cif = re.sub(r"^RO", "", (company_vat or "").strip(), flags=re.I)
    if not expected_cif.isdigit() or employer is None or employer.get("cif") != expected_cif:
        issues.append("CUI-ul angajatorului trebuie să coincidă cu firma selectată în Odoo.")
    xsd = etree.XMLSchema(schema_tree())
    if not xsd.validate(root):
        issues.extend(f"{e.path or 'XML'}: {e.message}" for e in xsd.error_log)
    seen = set()
    for person in root.findall("{" + NS + "}asigurat"):
        key = person.get("cnpAsig")
        if key and key in seen:
            issues.append("Același CNP/NIF apare în mai multe înregistrări de asigurat.")
        seen.add(key)
    return raw, issues


def fingerprint(raw):
    return hashlib.sha256(raw).hexdigest()


def semantic_equal(left, right):
    """Attribute order/whitespace do not affect the comparison; no values dropped."""
    def normalized(value):
        node = from_xml(value)
        return json.dumps(node, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return normalized(left) == normalized(right)

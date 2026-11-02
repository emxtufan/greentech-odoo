"""Synthetic XML fixtures for software tests, NEVER filing-ready declarations."""
def minimal(document, cif="12345674"):
    node = document.new_document(2026, 9, {
        "cif": cif, "caen": "6201", "den": "FIRMA FICTIVA TEST",
        "casaAng": "_B", "datCAM": "0", "totalPlata_A": "0",
    })
    node["attrs"].update(nume_declar="TEST", prenume_declar="TEHNIC", functie_declar="TEST")
    employer = node["children"][0]
    employer["children"][0]["attrs"] = {
        "A_codOblig": "602", "A_codBugetar": "20470101XX",
        "A_datorat": "0", "A_scutit": "0", "A_plata": "0",
    }
    employer["children"][1]["attrs"] = {
        "B_cnp": "0", "B_sanatate": "0", "B_pensie": "0", "B_sal": "0", "B_brutSalarii": "0",
    }
    return node


def with_person(document):
    root = minimal(document)
    person = document.empty_node("asigurat")
    person["attrs"] = {
        "idAsig": "1", "cnpAsig": "1990101010011", "numeAsig": "TEST", "prenAsig": "FICTIV",
        "dataAng": "01.09.2026", "asigCI": "1", "asigSO": "1", "Timp_E3": "0",
    }
    section = document.empty_node("asiguratA")
    schema = document.editor_schema()
    for node in [section, *person["children"]]:
        attrs = schema["types"][schema["tags"][node["tag"]]]["attributes"]
        for attr in attrs:
            if attr["required"]:
                node["attrs"][attr["name"]] = (attr.get("enumeration") or [attr.get("minInclusive", "0")])[0]
    person["children"].insert(0, section)
    root["children"].append(person)
    return root

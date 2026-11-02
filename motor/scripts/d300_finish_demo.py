"""After the user supplies the official ZIP: install, validate DEMO, generate PDF.

Never transmits/signs declarations and never changes accounting.
"""
import base64
import json
from pathlib import Path
import sys
from d300_resources import main as prepare, DEST
from financial_client import Client, ROOT


def main():
    prepare()
    if not (DEST / "lib/D300Validator.jar").is_file():
        raise RuntimeError("Lipsește arhiva ANAF. Salvați D300Validator_11022026_2.zip în Downloads.")
    c = Client()
    c.context["allowed_company_ids"] = [1]
    company = c.read("res.company", 1, ["name"])
    assert company["name"] == "GreenTech Financiar DEMO - date fictive"
    saved = json.loads((ROOT / "logs/d300-20261020/browser-live.json").read_text(encoding="utf-8"))
    record = saved["id"]
    c.call("ir.config_parameter", "set_param", ["gt_d300.duk_dir", str(DEST)])
    c.call("gt.anaf.d300", "action_validate", [[record]])
    state = c.read("gt.anaf.d300", record, ["state", "duk_log", "xsd_log"])
    print("D300_VALIDARE", state["state"])
    print(state["duk_log"] or state["xsd_log"])
    if state["state"] != "valid":
        raise RuntimeError("Validarea ANAF nu a confirmat succesul. Verificați fila Validări și fișiere.")
    c.call("gt.anaf.d300", "action_pdf", [[record]])
    data = c.read("gt.anaf.d300", record, ["state", "pdf_file", "xml_file", "validated_hash", "duk_log"])
    if data["state"] != "pdf":
        raise RuntimeError(data["duk_log"])
    output = ROOT / "output/pdf"
    output.mkdir(parents=True, exist_ok=True)
    (output / "D300_DEMO_2026_10.pdf").write_bytes(base64.b64decode(data["pdf_file"]))
    (output / "D300_DEMO_2026_10.xml").write_bytes(base64.b64decode(data["xml_file"]))
    print("D300_PDF_ANAF_GENERAT", output / "D300_DEMO_2026_10.pdf")
    print("Nu s-au semnat sau depus documente.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

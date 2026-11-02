"""Real local DUK integration: valid DEMO, invalid sum, embedded XML."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_addons/greentech_anaf_d112"))
from services import document, duk

work = ROOT / "logs/d112-java-20261020"
dist = ROOT / "tools/anaf/duk"
java = json.loads((work / "installation.json").read_text())["java_path"]
original = (ROOT / "logs/d112-demo-20261020/live-demo.xml").read_bytes()
assert not duk.readiness(dist, java)[1]
positive = duk.run(original, dist, java)
assert positive["status"] == "valid" and positive["report"].strip() == "ok", positive
payload = document.from_xml(original)
bad = deepcopy(payload)
employer = next(n for n in bad["children"] if n["tag"] == "angajator")
employer["attrs"]["totalPlata_A"] = "1"
negative = duk.run(document.to_xml(bad), dist, java)
assert negative["status"] == "invalid", negative
assert "E:" in negative["report"] or "F:" in negative["report"], negative
reader = PdfReader(ROOT / "output/pdf/D112_DEMO_2026_09.pdf")
attached = [b for values in reader.attachments.values() for b in values]
assert any(document.semantic_equal(original, b) for b in attached)
fields = reader.get_fields()
assert fields["totalPlata_A"]["/V"] == "14428"
assert fields["denumire"]["/V"] == "GreenTech Financiar DEMO - date fictive"
assert fields["universalCode"]["/V"] == "D112_J27.0.6"
widget_count = 0
for page in reader.pages:
    for ref in page.get("/Annots", []):
        widget = ref.get_object()
        if widget.get("/Subtype") != "/Widget":
            continue
        widget_count += 1
        field = widget.get("/Parent", widget).get_object()
        name = field.get("/T")
        if name in fields:
            assert field.get("/V") == fields[name].get("/V")
        assert widget.get("/AP", {}).get("/N"), name
report = {
    "positive": positive["status"], "positive_report": positive["report"],
    "negative": negative["status"], "negative_report": negative["report"],
    "pdf_pages": len(reader.pages), "embedded_xml_matches": True,
    "form_widgets_checked": widget_count,
    "validator_version": "D112_J27.0.6",
    "pdf_sha256": hashlib.sha256((ROOT / "output/pdf/D112_DEMO_2026_09.pdf").read_bytes()).hexdigest(),
}
(work / "integration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))

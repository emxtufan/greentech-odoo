"""Copy the public ANAF validator already installed with SAGA; no SAGA program code."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "custom_addons/greentech_anaf_d112"
SOURCE = Path(r"C:\SAGA C.3.0\FreeTab\dist")
DESTINATION = ROOT / "tools/anaf/duk"
FILES = (
    "DUKIntegrator.jar", "lib/D112Validator.jar", "lib/D112Pdf.jar",
    "lib/DecValidation.jar", "lib/DecPdf.jar", "lib/Validator.jar",
    "lib/iText-5.0.4.jar", "lib/bcprov-jdk15-145.jar", "lib/bcmail-jdk15-145.jar",
)


def prepare_runtime():
    hashes = {}
    for rel in FILES:
        raw = (SOURCE / rel).read_bytes()
        out = DESTINATION / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and out.read_bytes() != raw:
            raise RuntimeError("Existing ANAF runtime differs; explicit update needed: " + rel)
        out.write_bytes(raw)
        hashes[rel] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "source": str(SOURCE),
        "official_index": "https://static.anaf.ro/static/10/Anaf/Declaratii_R/112.html",
        "copied_at": datetime.now(timezone.utc).isoformat(),
        "note": "Local ANAF distribution used by SAGA. Hashes identify these files; not a certification of fiscal currency.",
        "files": hashes,
    }
    (DESTINATION / "runtime-lock.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("D112_ANAF_FILES_PINNED", len(hashes))


def labels():
    from pypdf import PdfReader
    from lxml import etree
    pdf = Path(r"C:\SAGA C.3.0\FreeTab\D112.pdf")
    reader = PdfReader(pdf)
    xfa = reader.trailer["/Root"]["/AcroForm"]["/XFA"]
    template = next(xfa[i + 1].get_object().get_data() for i in range(0, len(xfa), 2) if xfa[i] == "template")
    root = etree.fromstring(template, etree.XMLParser(resolve_entities=False, no_network=True))
    candidates = {}
    for field in root.xpath("//*[local-name()='field']"):
        name = field.get("name")
        if not name:
            continue
        parts = field.xpath("./*[local-name()='assist']/*[local-name()='toolTip']//text()")
        label = " ".join(" ".join(parts).split())
        if not label:
            parts = field.xpath("./*[local-name()='caption']/*[local-name()='value']//text()")
            label = " ".join(" ".join(parts).split())
        if label and len(label) < 600:
            candidates.setdefault(name, set()).add(label)
    # Ambiguous repeated field names keep their ANAF code rather than a wrong label.
    result = {k: next(iter(v)) for k, v in candidates.items() if len(v) == 1}
    (ADDON / "schemas/labels.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    source = {
        "schema_url": "https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/d112_0726_140826.xsd",
        "schema_sha256": hashlib.sha256((ADDON / "schemas/d112_0726.xsd").read_bytes()).hexdigest(),
        "labels_source": str(pdf), "labels_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "labels_pdf_modified": str(reader.metadata.get("/ModDate", "")),
    }
    (ADDON / "schemas/sources.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
    print("D112_LABELS_FROM_ANAF_FORM", len(result))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    prepare_runtime()
    labels()

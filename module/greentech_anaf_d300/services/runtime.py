"""Offline, isolated D300 DUK invocation. A missing/unknown validator never passes."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
from lxml import etree
from odoo.addons.greentech_anaf_d112.services.duk import report_status


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def readiness(dist, java):
    errors = []
    folder = Path(dist) if dist else None
    if not java or not Path(java).is_file():
        errors.append("Java nu este configurat.")
    if not folder or not (folder / "runtime-lock.json").is_file():
        return java, errors + ["Pachetul ANAF D300 nu este instalat. Descărcați arhiva oficială D300Validator_11022026_2.zip și instalați resursele."]
    try:
        lock = json.loads((folder / "runtime-lock.json").read_text(encoding="utf-8"))
        for rel in ("DUKIntegrator.jar", "lib/D300Validator.jar", "lib/D300Pdf.jar", "config/config.properties"):
            if rel not in lock["files"]:
                errors.append("Componentă ANAF absentă: " + rel)
        for rel, expected in lock["files"].items():
            p = folder / rel
            if not p.is_file() or sha(p.read_bytes()) != expected:
                errors.append("Resursă ANAF lipsă/modificată: " + rel)
    except (ValueError, KeyError, OSError):
        errors.append("Manifestul D300 nu poate fi verificat.")
    return java, errors


def validate_schema(raw, dist):
    folder = Path(dist) if dist else None
    path = folder / "schema/d300.xsd" if folder else None
    if not path or not path.is_file():
        return {"status": "unavailable", "report": "Schema XSD separată nu este instalată. Verificarea XSD separată nu a fost executată; rezultatul validării oficiale DUK este afișat mai jos."}
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        schema = etree.XMLSchema(etree.parse(str(path), parser))
        doc = etree.fromstring(raw, parser)
        ok = schema.validate(doc)
        return {"status": "valid" if ok else "invalid",
                "report": "Structură XSD ANAF v12 validă." if ok else str(schema.error_log)}
    except (etree.XMLSyntaxError, etree.XMLSchemaParseError, OSError) as exc:
        return {"status": "invalid", "report": str(exc)}


def run(raw, dist, java, make_pdf=False):
    executable, errors = readiness(dist, java)
    if errors:
        return {"status": "unavailable", "report": "\n".join(errors), "pdf": None}
    folder = Path(dist).resolve()
    with tempfile.TemporaryDirectory(prefix="gt-d300-") as temp:
        work = Path(temp)
        xml, report, pdf = [work / name for name in ("D300.xml", "result.txt", "D300.pdf")]
        xml.write_bytes(raw)
        command = [executable, "-Djava.awt.headless=true", "-Xmx512m", "-jar",
                   str(folder / "DUKIntegrator.jar"), "-p" if make_pdf else "-v",
                   "D300", str(xml), str(report), "0"]
        if make_pdf:
            command += ["0", str(pdf)]
        try:
            done = subprocess.run(command, cwd=folder, capture_output=True, timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "unavailable", "report": str(exc), "pdf": None}
        text = report.read_bytes().decode("utf-8-sig", errors="replace") if report.exists() else ""
        state = report_status(text)
        if done.returncode or state == "unknown":
            state = "invalid"
            text += "\nLipsește confirmarea explicită ANAF.\n" + (done.stdout + done.stderr).decode("utf-8", errors="replace")[-20000:]
        result = {"status": state, "report": text, "pdf": None}
        if make_pdf and state == "valid":
            try:
                from pypdf import PdfReader
                if not pdf.exists() or not pdf.read_bytes().startswith(b"%PDF-"):
                    raise ValueError("ANAF nu a produs un PDF.")
                reader = PdfReader(BytesIO(pdf.read_bytes()))
                parser = etree.XMLParser(resolve_entities=False, no_network=True)
                source = etree.fromstring(raw, parser)
                matched = False
                for values in reader.attachments.values():
                    for content in values:
                        try:
                            attached = etree.fromstring(content, parser)
                            matched |= attached.tag == source.tag and dict(attached.attrib) == dict(source.attrib)
                        except etree.XMLSyntaxError:
                            pass
                if not matched:
                    raise ValueError("XML-ul din PDF nu corespunde declarației validate.")
                result["pdf"] = pdf.read_bytes()
            except Exception as exc:
                result.update(status="invalid", report="Verificare PDF/XML: " + str(exc))
        return result

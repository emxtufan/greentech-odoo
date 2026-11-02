"""Invoke the ANAF program locally; never infer success from the exit code alone."""
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .document import fingerprint, semantic_equal

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DEFAULT = REPO_ROOT / "motor" / "tools" / "anaf"


def _param(env, key):
    return (env["ir.config_parameter"].sudo().get_param(key, "") or "").strip()


def resolve_duk_dir(env, key, sub):
    p = _param(env, key)
    if p and Path(p).is_dir():
        return p
    base = _param(env, "gt_anaf.tools_dir")
    base = Path(base) if base and Path(base).is_dir() else TOOLS_DEFAULT
    return str(base / sub)


def resolve_java(env):
    p = _param(env, "gt_anaf.java_path")
    if p and Path(p).is_file():
        return p
    found = shutil.which("java")
    if found:
        return found
    bundled = REPO_ROOT / "motor" / "tools" / "java" / "jdk8u504-b01" / "bin" / "java.exe"
    return str(bundled) if bundled.is_file() else ""


REQUIRED = (
    "DUKIntegrator.jar", "lib/D112Validator.jar", "lib/D112Pdf.jar",
    "lib/DecValidation.jar", "lib/DecPdf.jar", "lib/Validator.jar",
    "lib/iText-5.0.4.jar", "lib/bcprov-jdk15-145.jar", "lib/bcmail-jdk15-145.jar",
    "config/config.properties",
)


def readiness(dist, java=""):
    folder = Path(dist)
    executable = java or shutil.which("java") or ""
    problems = []
    if not executable or not Path(executable).is_file():
        problems.append("Java nu este instalat sau nu este configurat pe serverul Odoo.")
    lock = folder / "runtime-lock.json"
    if not lock.is_file():
        problems.append("Pachetul DUKIntegrator nu are manifestul local verificat.")
    else:
        try:
            hashes = json.loads(lock.read_text(encoding="utf-8"))["files"]
            for rel in REQUIRED:
                path = folder / rel
                if not path.is_file() or fingerprint(path.read_bytes()) != hashes.get(rel):
                    problems.append("Fișier ANAF absent sau modificat: " + rel)
        except (OSError, ValueError, KeyError):
            problems.append("Manifestul validatorului nu poate fi citit.")
    return executable, problems


def report_status(text):
    text = text.strip()
    if text.lower() == "ok":
        return "valid"
    markers = re.findall(r"^\s*([EFWA]):", text, flags=re.M)
    if "E" in markers or "F" in markers:
        return "invalid"
    # ANAF warnings need a separate user review, not a silent green check.
    if markers and set(markers) <= {"W", "A"}:
        return "warnings"
    return "unknown"


def run(raw, dist, java="", make_pdf=False):
    executable, problems = readiness(dist, java)
    if problems:
        return {"status": "unavailable", "report": "\n".join(problems), "pdf": None}
    folder = Path(dist).resolve()
    with tempfile.TemporaryDirectory(prefix="odoo-d112-") as temporary:
        work = Path(temporary)
        xml = work / "declaratie.xml"
        errors = work / "rezultat.txt"
        pdf = work / "declaratie.pdf"
        xml.write_bytes(raw)
        command = [
            executable, "-Djava.awt.headless=true", "-Xmx512m", "-jar",
            str(folder / "DUKIntegrator.jar"), "-p" if make_pdf else "-v",
            "D112", str(xml), str(errors), "0",
        ]
        if make_pdf:
            command.extend(["0", str(pdf)])
        try:
            completed = subprocess.run(
                command, cwd=folder, capture_output=True, timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return {"status": "unavailable", "report": "Validatorul ANAF a depășit limita de 120 secunde.", "pdf": None}
        except OSError as exc:
            return {"status": "unavailable", "report": "Validatorul nu a putut porni: " + str(exc), "pdf": None}
        output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")[-50000:]
        report = errors.read_bytes().decode("utf-8-sig", errors="replace")[:1000000] if errors.is_file() else ""
        state = report_status(report)
        if completed.returncode != 0 or state == "unknown":
            return {"status": "invalid", "report": report + "\n" + output + "\nLipsește confirmarea explicită ANAF.", "pdf": None}
        result = {"status": state, "report": report, "pdf": None,
                  "runtime": json.loads((folder / "runtime-lock.json").read_text())["files"],
                  "xml_hash": fingerprint(raw)}
        if make_pdf and state == "valid":
            if not pdf.is_file() or not pdf.read_bytes().startswith(b"%PDF-"):
                return {"status": "invalid", "report": "DUKIntegrator nu a produs un PDF valid.", "pdf": None}
            try:
                from pypdf import PdfReader
                reader = PdfReader(BytesIO(pdf.read_bytes()))
                attachments = [b for values in reader.attachments.values() for b in values]
                matched = False
                for value in attachments:
                    try:
                        matched = matched or semantic_equal(raw, value)
                    except ValueError:
                        continue
                if not matched:
                    raise ValueError("XML-ul atașat în PDF nu corespunde declarației validate.")
            except Exception as exc:
                return {"status": "invalid", "report": "Verificarea PDF/XML a eșuat: " + str(exc), "pdf": None}
            result["pdf"] = pdf.read_bytes()
        return result

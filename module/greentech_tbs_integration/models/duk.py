"""Isolated, offline ANAF processes; never sign or submit a declaration."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from lxml import etree
from odoo import api, models
from odoo.exceptions import AccessError

ROOT = Path(__file__).resolve().parents[3]


class Duk(models.AbstractModel):
    _inherit = "anaf.duk.validator"

    @api.private
    @api.model
    def get_duk_path(self):
        return str(ROOT / "tools/anaf/d406")

    @api.model
    def _java_executable(self):
        """Use a Java runtime from PATH, with the bundled Windows JDK as fallback."""
        java = shutil.which("java")
        if java:
            return java
        bundled = ROOT / "tools/java/jdk8u504-b01/bin/java.exe"
        return str(bundled) if bundled.is_file() else None

    @api.private
    @api.model
    def check_installation(self):
        path = Path(self.get_duk_path())
        jar = self._find_jar(str(path))
        installed = bool(jar and self._java_executable())
        return {"installed": installed, "path": str(path), "jar": jar,
                "message": "DUK D406 local, Java portabil; funcționare offline."
                if installed else "Lipsesc componentele runtime D406 sau Java."}

    @api.private
    @api.model
    def validate(self, xml_content, duk_code, year=None, month=None):
        return self._run(xml_content, duk_code, "validate", year, month)

    @api.private
    @api.model
    def generate_pdf(self, xml_content, duk_code, year=None, month=None):
        return self._run(xml_content, duk_code, "pdf", year, month)

    def _run(self, xml_content, duk_code, mode, year=None, month=None):
        if not self.env.user.has_group("account.group_account_manager"):
            raise AccessError("Validarea declarațiilor necesită drepturi de contabil.")
        failure = lambda text: {"success": False, "errors": text}
        if duk_code not in ("D406", "D300", "D112") or mode not in ("validate", "pdf"):
            return failure("Declarație sau operație neacceptată.")
        if not isinstance(year, int) or not 2000 <= year <= 2100 or not isinstance(month, int) or not 1 <= month <= 12:
            return failure("Anul și luna raportării sunt obligatorii.")
        raw = xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content
        if not isinstance(raw, bytes) or not raw or len(raw) > 50 * 1024 * 1024:
            return failure("XML lipsă sau peste limita locală de 50 MB.")
        try:
            document = etree.fromstring(raw, etree.XMLParser(
                resolve_entities=False, load_dtd=False, no_network=True))
            if document.getroottree().docinfo.doctype:
                return failure("Declarațiile nu pot conține DTD sau entități externe.")
        except (ValueError, etree.XMLSyntaxError) as exc:
            return failure("XML invalid: " + str(exc))
        folder = {"D406": "d406", "D300": "d300", "D112": "duk"}[duk_code]
        runtime = ROOT / "tools/anaf" / folder
        java = self._java_executable()
        jar = self._find_jar(str(runtime))
        if not jar or not java:
            return failure("Lipsește runtime-ul local pentru " + duk_code)
        # D406 components must match the reviewed copy, including offline config.
        if duk_code == "D406":
            try:
                lock = json.loads((runtime / "runtime-lock.json").read_text(encoding="utf-8"))
                for name, expected in lock["files"].items():
                    path = (runtime / name).resolve()
                    if not path.is_relative_to(runtime.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                        return failure("Componentă D406 modificată: " + name)
            except (OSError, ValueError, KeyError) as exc:
                return failure("Runtime D406 neverificat: " + str(exc))
        with tempfile.TemporaryDirectory(prefix="gt-duk-") as temp:
            tmp = Path(temp)
            xml, errors, pdf = tmp / "declaration.xml", tmp / "errors.txt", tmp / "output.pdf"
            xml.write_bytes(raw)
            cmd = [java, "-Xmx512m", "-Djava.awt.headless=true", "-jar", jar,
                   "-p" if mode == "pdf" else "-v", duk_code, str(xml), str(errors), "0"]
            if mode == "pdf":
                cmd += ["0", str(pdf)]
            if "AnLunaUI" in jar:
                cmd += [f"an={year}", f"luna={month}"]
            if duk_code == "D406":
                declaration_type = document.findtext("{*}Header/{*}HeaderComment")
                if declaration_type not in ("L", "T", "NL", "NT"):
                    return failure("Tipul declarației D406 periodice lipsește sau este invalid.")
                cmd = [java, "-Xmx512m", "-Djava.awt.headless=true",
                       "-cp", str(runtime) + os.pathsep + str(runtime / "lib/*"),
                       "GtD406Runner", mode, "D406", str(xml), str(errors), str(pdf),
                       str(year), str(month), declaration_type]
            try:
                proc = subprocess.run(cmd, cwd=runtime, capture_output=True, timeout=120,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.TimeoutExpired) as exc:
                return failure("Validatorul nu a terminat: " + str(exc))
            report = errors.read_text(encoding="utf-8", errors="replace").strip() if errors.exists() else ""
            if proc.returncode or report.lower() != "ok":
                diagnostic = report or (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
                return failure(diagnostic[:40000] or "Validatorul nu a produs confirmarea «ok».")
            if duk_code == "D406" and b"GT_D406_ANAF_VALID" not in proc.stdout:
                return failure("Lipsește confirmarea execuției validatorului ANAF pentru perioada selectată.")
            result = {"success": True, "message": "DUK local: validare fără erori (nu reprezintă depunere)."}
            if mode == "pdf":
                if not pdf.exists() or not pdf.read_bytes().startswith(b"%PDF-"):
                    return failure("DUK nu a produs un PDF valid.")
                result["pdf_data"] = pdf.read_bytes()
            return result

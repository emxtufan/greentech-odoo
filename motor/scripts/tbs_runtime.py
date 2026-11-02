"""Assemble an isolated offline D406 runtime from existing ANAF components."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / "tools/anaf/d406"
target.mkdir(exist_ok=True)
(target / "lib").mkdir(exist_ok=True)
(target / "config").mkdir(exist_ok=True)
source = ROOT / "tools/anaf/d300"
for path in [source / "DUKIntegrator.jar", *list((source / "lib").glob("*.jar"))]:
    if path.name.startswith("D300"):
        continue
    dest = target / path.relative_to(source)
    shutil.copy2(path, dest)
official_local = Path(r"C:\SAGA C.3.0\FreeTab\dist\lib")
for name in ("D406Validator.jar", "D406Pdf.jar"):
    shutil.copy2(official_local / name, target / "lib" / name)
(target / "config/config.properties").write_text(
    "offLine=Y\ntipDeclaratie=D406\n_D406=optiune standard\n", encoding="ascii")
subprocess.run([str(ROOT / "tools/java/jdk8u504-b01/bin/javac.exe"),
                "-encoding", "UTF-8", "-classpath", str(target / "lib/*"),
                str(target / "GtD406Runner.java")], check=True, capture_output=True)
files = {
    p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(target.rglob("*")) if p.is_file() and p.name != "runtime-lock.json"
}
(target / "runtime-lock.json").write_text(json.dumps({
    "source": "Existing local ANAF DUK shared libraries; D406 jars from SAGA C.3.0/FreeTab/dist/lib. No business data imported.",
    "latest_official_binary_identity_verified": False,
    "launcher": "GtD406Runner calls unchanged ANAF Validator.parseDocument(xml, errors, year, month, type) and Pdf_v0.createPdf; legacy DUK launcher cannot supply the period.",
    "files": files,
}, indent=2), encoding="utf-8")
print("D406_OFFLINE_RUNTIME", len(files))

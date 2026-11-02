"""Prepare only public ANAF resources supplied by the user; preserve D112 runtime."""
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "tools/anaf/d300"
DOWNLOADS = Path(r"C:\Users\GPRO\Downloads")
URL = "https://static.anaf.ro/static/10/Anaf/Declaratii_R/AplicatiiDec/D300Validator_11022026_2.zip"


def main():
    archives = sorted(DOWNLOADS.glob("D300Validator_11022026_2*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not archives:
        print("D300_RESOURCE_PENDING", URL)
        return
    archive = archives[0]
    files = {}
    # Shared original ANAF libraries already verified for the installed Java8 runtime.
    existing = ROOT / "tools/anaf/duk"
    for p in existing.rglob("*.jar"):
        if "D112" not in p.name:
            files[p.relative_to(existing).as_posix()] = p.read_bytes()
    schemas = []
    with ZipFile(archive) as z:
        for entry in z.infolist():
            name = Path(entry.filename).name
            if entry.file_size > 150_000_000:
                raise ValueError("Unexpected archive member size")
            if name in ("D300Validator.jar", "D300Pdf.jar"):
                files["lib/" + name] = z.read(entry)
            if name.lower().endswith((".xsd", ".xml")):
                raw = z.read(entry)
                if b"targetNamespace" in raw and b"declaratie:v12" in raw:
                    schemas.append(raw)
    for name in ("D300Validator.jar", "D300Pdf.jar"):
        if "lib/" + name not in files:
            raise ValueError("Official archive missing " + name)
    # Many ANAF distributions package their XSD inside the validator JAR.
    from io import BytesIO
    with ZipFile(BytesIO(files["lib/D300Validator.jar"])) as jar:
        for name in jar.namelist():
            if name.lower().endswith((".xsd", ".xml")):
                raw = jar.read(name)
                if b"targetNamespace" in raw and b"declaratie:v12" in raw:
                    schemas.append(raw)
    for p in DOWNLOADS.glob("d300_v12_11022026*"):
        raw = p.read_bytes()
        if b"targetNamespace" in raw and b"declaratie:v12" in raw:
            schemas.append(raw)
    if schemas:
        files["schema/d300.xsd"] = schemas[0]
    files["config/config.properties"] = b"offLine=Y\ntipDeclaratie=D300\n_D300=optiune standard\n"
    for rel, raw in files.items():
        dest = DEST / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    lock = {"source": URL, "archive": archive.name,
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "files": {rel: hashlib.sha256(raw).hexdigest() for rel, raw in files.items()}}
    (DEST / "runtime-lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
    print("D300_RESOURCES_READY", len(files), "XSD", bool(schemas))

if __name__ == "__main__":
    main()

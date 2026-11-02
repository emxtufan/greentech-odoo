"""Install the user-supplied portable JDK within this project."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
archive = Path(r"C:\Users\GPRO\Downloads\OpenJDK8U-jdk_x64_windows_hotspot_8u504b01.zip")
destination = ROOT / "tools/java"
destination.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as bundle:
    for item in bundle.infolist():
        target = (destination / item.filename).resolve()
        assert target.is_relative_to(destination.resolve()), "Unsafe ZIP path"
        assert (item.external_attr >> 16) & 0o170000 != 0o120000, "Unexpected symlink"
    assert bundle.testzip() is None, "Corrupt ZIP"
    bundle.extractall(destination)
java = list(destination.glob("jdk8u504-b01/bin/java.exe"))
assert len(java) == 1
report = {
    "archive": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "java_path": str(java[0]), "scope": "project-local portable JDK",
}
out = ROOT / "logs/d112-java-20261020"
out.mkdir(exist_ok=True)
(out / "installation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))

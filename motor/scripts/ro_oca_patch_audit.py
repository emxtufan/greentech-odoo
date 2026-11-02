"""Record local changes separately from the verified upstream Git blobs."""
import base64
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "logs/oca-ro-install-20261020"
patches = []
diffs = []
known = set()
for bundle in (WORK / "sources").glob("*.json"):
    for item in json.loads(bundle.read_text(encoding="utf-8")):
        target = ROOT / "third_party_addons" / item["destination"] / item["path"]
        known.add(target)
        before = base64.b64decode(item["content"]) if item["encoding"] == "base64" else item["content"].encode()
        after = target.read_bytes()
        if before == after:
            continue
        rel = target.relative_to(ROOT).as_posix()
        diffs.extend(difflib.unified_diff(
            before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True),
            fromfile="a/" + rel, tofile="b/" + rel,
        ))
        patches.append({"file": rel, "upstream_git_sha1": item["sha"],
                        "local_sha256": hashlib.sha256(after).hexdigest()})
for base in ("oca-ro-19", "bank-statement-import"):
    for target in (ROOT / "third_party_addons" / base).rglob("*.py"):
        if target in known:
            continue
        rel = target.relative_to(ROOT).as_posix()
        after = target.read_bytes()
        diffs.extend(difflib.unified_diff([], after.decode().splitlines(keepends=True),
                                         fromfile="/dev/null", tofile="b/" + rel))
        patches.append({"file": rel, "upstream_git_sha1": None,
                        "local_sha256": hashlib.sha256(after).hexdigest()})
(WORK / "local-patches.json").write_text(json.dumps(patches, indent=2), encoding="utf-8")
(WORK / "local-patches.patch").write_text("".join(diffs), encoding="utf-8")
print("OCA_LOCAL_PATCHES_RECORDED", len(patches))

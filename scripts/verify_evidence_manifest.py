import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest_path = root / "EVIDENCE_MANIFEST.json"
sidecar = (root / "EVIDENCE_MANIFEST.sha256").read_text(encoding="ascii").strip()
payload = manifest_path.read_bytes()
assert hashlib.sha256(payload).hexdigest() == sidecar, "manifest sidecar mismatch"
manifest = json.loads(payload)
bad = []
for item in manifest["artifacts"]:
    path = Path(item["path"])
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        bad.append((item["path"], "missing"))
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != item["sha256"]:
        bad.append((item["path"], "hash"))
print(json.dumps({
    "status": manifest["evidence_status"],
    "artifacts": len(manifest["artifacts"]),
    "bad": bad,
    "manifest_sha256": sidecar,
}, indent=2))
sys.exit(0 if not bad and manifest["evidence_status"] == "COMPLETE" else 1)

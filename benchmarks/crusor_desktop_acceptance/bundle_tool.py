"""P0.6.4.1 — baseline / verification helpers for the bundle regeneration.

Records sha256 of every file under the Crusor desktop bundle (tracked or not),
so the regeneration diff can be stated precisely and media byte-identity can be
proven rather than asserted.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "desktop" / "vscode" / "out" / "vs" / "workbench" / "contrib" / "crusorai"
SRC = REPO / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"
EVIDENCE = REPO / "diagnostics" / "p0_6_4_1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): sha256(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, timeout=180
    ).stdout.strip()


def cmd_baseline() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    data = {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "bundle_files": snapshot(BUNDLE),
        "src_files": snapshot(SRC),
        "tracked_bundle_count": len(git("ls-files", str(BUNDLE.relative_to(REPO))).splitlines()),
        "dirty_outside_bundle": [
            line for line in git("status", "--porcelain").splitlines()
            if "desktop/vscode/out/vs/workbench/contrib/crusorai" not in line
        ],
    }
    (EVIDENCE / "baseline.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    print(f"branch={data['branch']} head={data['head'][:8]}")
    print(f"bundle files={len(data['bundle_files'])} tracked={data['tracked_bundle_count']}")
    print(f"src files={len(data['src_files'])}")
    print(f"dirty entries outside bundle={len(data['dirty_outside_bundle'])}")
    return 0


def cmd_verify() -> int:
    baseline = json.loads((EVIDENCE / "baseline.json").read_text(encoding="utf-8"))
    before: dict[str, str] = baseline["bundle_files"]
    after = snapshot(BUNDLE)

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(p for p in set(before) & set(after) if before[p] != after[p])

    # Media byte-identity: every non-.js/.json artifact in the bundle must equal
    # its counterpart in src/ byte for byte.
    media_mismatch = []
    media_checked = 0
    for rel in after:
        if rel.endswith((".js", ".json")):
            continue
        src_file = SRC / rel
        if not src_file.exists():
            continue
        media_checked += 1
        if sha256(src_file) != after[rel]:
            media_mismatch.append(rel)

    sources_hash = (BUNDLE / "browser" / "SOURCES_HASH")
    manifest_file = BUNDLE / "browser" / "SOURCES_MANIFEST.json"
    build_info = BUNDLE / "browser" / "BUILD_INFO.json"

    changed_paths = git("status", "--porcelain", "--", str(BUNDLE.relative_to(REPO)))
    outside = [
        line for line in git("status", "--porcelain").splitlines()
        if "desktop/vscode/out/vs/workbench/contrib/crusorai" not in line
    ]

    report = {
        "added": added,
        "removed": removed,
        "modified": modified,
        "counts": {"added": len(added), "removed": len(removed), "modified": len(modified)},
        "media_checked": media_checked,
        "media_mismatch": media_mismatch,
        "sources_hash": sources_hash.read_text(encoding="utf-8").strip() if sources_hash.exists() else None,
        "sources_manifest_present": manifest_file.exists(),
        "build_info": json.loads(build_info.read_text(encoding="utf-8")) if build_info.exists() else None,
        "git_status_bundle": changed_paths,
        "dirty_outside_bundle": outside,
    }
    (EVIDENCE / "regeneration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"added={len(added)} removed={len(removed)} modified={len(modified)}")
    print(f"media checked={media_checked} mismatches={len(media_mismatch)}")
    print(f"SOURCES_HASH={report['sources_hash']}")
    print(f"SOURCES_MANIFEST present={report['sources_manifest_present']}")
    print(f"BUILD_INFO={report['build_info']}")
    print(f"git status lines for bundle={len(changed_paths.splitlines())}")
    print(f"dirty entries outside bundle changed? {[o for o in outside][:3]}")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if arg == "baseline":
        sys.exit(cmd_baseline())
    if arg == "snapshot":
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        name = sys.argv[2] if len(sys.argv) > 2 else "snapshot"
        data = snapshot(BUNDLE)
        (EVIDENCE / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"snapshot {name}: {len(data)} files")
        sys.exit(0)
    if arg == "compare":
        a = json.loads((EVIDENCE / f"{sys.argv[2]}.json").read_text(encoding="utf-8"))
        b = snapshot(BUNDLE)
        diff = [p for p in set(a) | set(b) if a.get(p) != b.get(p)]
        print(f"compare {sys.argv[2]} -> now: {len(diff)} differing file(s)")
        for p in diff[:10]:
            print("  ", p)
        sys.exit(0 if not diff else 1)
    sys.exit(cmd_verify())

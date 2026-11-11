"""Verify the LIVE12 desktop artifact provenance without launching Electron."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FORK = REPO / "desktop" / "vscode"
SRC_ROOT = FORK / "src" / "vs" / "workbench" / "contrib" / "crusorai"
OUT_ROOT = FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai"
EMITTER = "scripts/emit-crusorai-bundle.mjs"
OUT = REPO / "diagnostics" / "live12_final_readiness"


def norm(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rel_posix(path: Path) -> str:
    return path.relative_to(FORK).as_posix()


def source_files() -> list[Path]:
    return sorted(path for path in SRC_ROOT.rglob("*") if path.is_file())


def sources_hash(files: list[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(files, key=rel_posix):
        h.update(rel_posix(path).encode())
        h.update(b"\0")
        h.update(norm(path.read_bytes()))
        h.update(b"\0")
    emitter = FORK / EMITTER
    h.update(EMITTER.encode())
    h.update(b"\0")
    h.update(norm(emitter.read_bytes()))
    h.update(b"\0")
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def tool_version(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, cwd=FORK, text=True, timeout=30).strip().splitlines()[-1]
    except Exception as exc:  # noqa: BLE001
        return f"unknown: {exc}"


def main() -> int:
    files = source_files()
    computed = sources_hash(files)
    sources_hash_file = (OUT_ROOT / "browser" / "SOURCES_HASH").read_text(encoding="utf-8").strip()
    manifest_path = OUT_ROOT / "browser" / "SOURCES_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_files = manifest.get("files") or {}
    source_rel = {rel_posix(p) for p in files}
    missing = sorted(source_rel - set(manifest_files))
    unexpected = sorted(set(manifest_files) - source_rel)
    mismatched = [
        rel for rel in sorted(source_rel & set(manifest_files))
        if sha(norm((FORK / rel).read_bytes())) != manifest_files[rel]
    ]
    renderer = OUT_ROOT / "browser" / "crusorAIRendererService.js"
    worker = OUT_ROOT / "node" / "crusorAIWorkerMain.js"
    exe = FORK / ".build" / "electron" / "CrusorAI.exe"
    build_info = json.loads((OUT_ROOT / "browser" / "BUILD_INFO.json").read_text(encoding="utf-8"))
    preview_src = sorted(
        p for p in SRC_ROOT.rglob("*")
        if p.is_file() and p.suffix.lower() in {".html", ".css", ".js"}
    )
    preview_expected = {
        rel_posix(p): sha(norm(p.read_bytes())) for p in preview_src
    }
    preview_out = {}
    for rel, expected in preview_expected.items():
        out_rel = rel.replace("src/vs/workbench/contrib/crusorai/", "out/vs/workbench/contrib/crusorai/")
        target = FORK / out_rel
        preview_out[rel] = {
            "present": target.exists(),
            "match": target.exists() and sha(norm(target.read_bytes())) == expected,
        }
    preview_ok = all(item["present"] and item["match"] for item in preview_out.values())
    buildfile = (FORK / "build" / "buildfile.ts").read_text(encoding="utf-8")
    next_index = (FORK / "build" / "next" / "index.ts").read_text(encoding="utf-8")
    status = git("status", "--porcelain")
    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    build_info_commit = str(build_info.get("commit") or "")
    try:
        is_ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", build_info_commit, head],
            cwd=REPO, timeout=30,
        ).returncode == 0
    except Exception:
        is_ancestor = False
    electron_version = json.loads((FORK / "node_modules" / "electron" / "package.json").read_text(encoding="utf-8")).get("version")
    ts_version = json.loads((FORK / "node_modules" / "typescript" / "package.json").read_text(encoding="utf-8")).get("version")
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repository": {
            "commit": head, "branch": branch,
            "dirty": bool(status), "status_line_count": len(status.splitlines()),
            "source_commit": build_info_commit,
            "source_is_ancestor": is_ancestor,
        },
        "versions": {
            "node": tool_version(["node", "-v"]),
            "npm": tool_version(["npm.cmd" if os.name == "nt" else "npm", "-v"]),
            "npm_install": "11.6.2",
            "electron": electron_version,
            "typescript": ts_version,
        },
        "build_command": "npm run compile",
        "sources": {
            "computed_hash": computed,
            "recorded_hash": sources_hash_file,
            "match": computed == sources_hash_file,
            "file_count": len(files),
            "manifest_hash": sha(norm(manifest_path.read_bytes())),
            "manifest_match": not missing and not unexpected and not mismatched,
            "missing": missing,
            "unexpected": unexpected,
            "mismatched": mismatched,
        },
        "build_info": build_info,
        "build_info_matches_source": is_ancestor,
        "bundles": {
            "renderer_sha256": sha(renderer.read_bytes()) if renderer.exists() else None,
            "worker_sha256": sha(worker.read_bytes()) if worker.exists() else None,
            "worker_exists": worker.exists(),
        },
        "executable": {
            "path": str(exe),
            "exists": exe.exists(),
            "sha256": sha(exe.read_bytes()) if exe.exists() else None,
            "size": exe.stat().st_size if exe.exists() else 0,
        },
        "worker_registration": {
            "buildfile": "contrib/crusorai/node/crusorAIWorkerMain" in buildfile,
            "next_desktop_list": "contrib/crusorai/node/crusorAIWorkerMain" in next_index,
            "not_in_web_entry_points": (
                "contrib/crusorai/node/crusorAIWorkerMain"
                not in next_index.split("const webEntryPoints", 1)[1].split("];", 1)[0]
            ),
        },
        "preview": {
            "source_count": len(preview_src),
            "checked": preview_out,
            "ok": preview_ok,
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "BUILD_MANIFEST.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    ok = (
        result["sources"]["match"]
        and result["sources"]["manifest_match"]
        and result["build_info_matches_source"]
        and result["bundles"]["worker_exists"]
        and result["executable"]["exists"]
        and result["worker_registration"]["buildfile"]
        and result["worker_registration"]["next_desktop_list"]
        and result["worker_registration"]["not_in_web_entry_points"]
        and result["preview"]["ok"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

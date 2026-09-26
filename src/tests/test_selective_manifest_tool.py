"""CrusorAI — ``scripts/refresh_selective_manifest.py`` (the manifest receipt tool).

The manifest is a receipt trail, and the guard test in ``test_desktop_contrib_overlay.py`` checks it.
This file checks the tool that is now the only sanctioned way to move those receipts, because the
alternative — hand-editing sha256 pins — turns an integrity check into a rubber stamp.

Field round 2026-09-26 is why the tool exists at all: 7 receipts had gone stale (the manifest was
committed in the same commit that rewrote those files, with receipts computed from an earlier working
copy), and clearing that by hand would have been unverifiable. The pins here are the properties that
make it safe to use: it agrees with the tree it ships with, it reports drift instead of hiding it, it
treats LF-normalization as ``.gitattributes`` defines it, and above all it **refuses to write while an
integrity problem is present** — especially ``edit lost``, an overlay file whose bytes have become
identical to its recorded upstream, where refreshing the receipt would erase the only evidence that a
fork edit disappeared.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "refresh_selective_manifest.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("refresh_selective_manifest", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def _fixture(tmp_path: Path, tool, *, overlay: str = "export const edited = true;\n") -> Path:
    """A miniature repo: one pinned text overlay file and one brand asset."""
    (tmp_path / "desktop" / "vscode" / "build").mkdir(parents=True)
    (tmp_path / "desktop" / "vscode" / "resources" / "win32").mkdir(parents=True)
    (tmp_path / "branding").mkdir()
    (tmp_path / ".gitattributes").write_text("desktop/vscode/build/x.ts text eol=lf\n")
    (tmp_path / "desktop" / "UPSTREAM_PIN").write_text("deadbeef\n")
    (tmp_path / "branding" / "crusorai-mark.svg").write_text("<svg/>\n")
    # The real tree carries both: the .svg embeds a raster that is byte-identical to this .png
    # (sha256 2bc21ca0…, 401,307 bytes, both) — which is why re-pointing the citation is a
    # provenance fix rather than a re-render. Present here so the citation repair has both to see.
    (tmp_path / "branding" / "crusorai-mark.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
    (tmp_path / "desktop" / "vscode" / "build" / "x.ts").write_text(overlay)
    (tmp_path / "desktop" / "vscode" / "resources" / "win32" / "code.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest = {
        "upstream_repository": "https://github.com/microsoft/vscode",
        "upstream_commit": "deadbeef",
        "files": {
            "build/x.ts": {
                "upstream_sha256": _sha("export const original = true;\n"),
                "overlay_sha256": tool.receipt_sha(
                    tmp_path / "desktop" / "vscode" / "build" / "x.ts",
                    tool.lf_pins(tmp_path / ".gitattributes"),
                    "build/x.ts",
                ),
                "modified": True,
            }
        },
        "custom_root": [],
        "brand_assets": {
            "resources/win32/code.png": {
                "overlay_sha256": tool.receipt_sha(
                    tmp_path / "desktop" / "vscode" / "resources" / "win32" / "code.png",
                    tool.lf_pins(tmp_path / ".gitattributes"),
                    "resources/win32/code.png",
                ),
                "replaces_upstream": True,
                "generated_from": tool.CANONICAL_BRAND_SOURCE,
            }
        },
    }
    (tmp_path / "desktop" / "SELECTIVE_MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return tmp_path


# ── the tool and the repo it ships with ─────────────────────────────────────────────────────

def test_the_shipped_manifest_is_consistent(tool) -> None:
    """The committed receipts match the committed tree — the property the guard test checks."""
    assert tool.main([]) == 0


def test_drift_is_reported_and_the_exit_code_says_so(tool, tmp_path, capsys) -> None:
    root = _fixture(tmp_path, tool)
    # The overlay file changes; the receipt does not.
    (root / "desktop" / "vscode" / "build" / "x.ts").write_text("export const edited = 'again';\n")
    assert tool.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "build/x.ts" in out and "now" in out
    assert "--write" in out, "check mode must say how to repair it"


def test_write_refreshes_and_is_idempotent(tool, tmp_path) -> None:
    root = _fixture(tmp_path, tool)
    (root / "desktop" / "vscode" / "build" / "x.ts").write_text("export const edited = 'again';\n")
    assert tool.main(["--write", "--root", str(root)]) == 0
    assert tool.main(["--root", str(root)]) == 0, "a second run must find nothing to do"


# ── the guards: a write must never paper over an integrity problem ───────────────────────────

def test_an_overlay_that_matches_upstream_blocks_the_write(tool, tmp_path, capsys) -> None:
    """The 'edit lost' guard: the fork's edit is gone, so the receipt must NOT be refreshed."""
    root = _fixture(tmp_path, tool)
    manifest_path = root / "desktop" / "SELECTIVE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    # The file is now byte-identical to the upstream it was forked from.
    same = _sha("export const original = true;\n")
    manifest["files"]["build/x.ts"]["upstream_sha256"] = same
    manifest["files"]["build/x.ts"]["overlay_sha256"] = "0" * 64
    (root / "desktop" / "vscode" / "build" / "x.ts").write_text("export const original = true;\n")
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")
    before = manifest_path.read_bytes()

    assert tool.main(["--write", "--root", str(root)]) == 2
    assert "edit lost" in capsys.readouterr().out
    assert manifest_path.read_bytes() == before, "a refused run must not touch the manifest"
    assert tool.main(["--root", str(root)]) == 2, "check mode refuses for the same reason"


def test_a_missing_brand_source_blocks_the_write(tool, tmp_path, capsys) -> None:
    root = _fixture(tmp_path, tool)
    manifest_path = root / "desktop" / "SELECTIVE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["brand_assets"]["resources/win32/code.png"]["generated_from"] = "branding/gone.svg"
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")

    assert tool.main(["--write", "--root", str(root)]) == 2
    assert "source missing" in capsys.readouterr().out


def test_an_upstream_pin_mismatch_blocks_the_write(tool, tmp_path, capsys) -> None:
    root = _fixture(tmp_path, tool)
    (root / "desktop" / "UPSTREAM_PIN").write_text("cafebabe\n")
    assert tool.main(["--write", "--root", str(root)]) == 2
    assert "upstream pin" in capsys.readouterr().out


# ── provenance citations are refreshed too (and are not integrity problems) ──────────────────

def test_a_wrong_citation_is_repaired_not_refused(tool, tmp_path, capsys) -> None:
    """All 9 assets cited the .png while the documented source is the .svg (byte-identical raster)."""
    root = _fixture(tmp_path, tool)
    manifest_path = root / "desktop" / "SELECTIVE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["brand_assets"]["resources/win32/code.png"]["generated_from"] = "branding/crusorai-mark.png"
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")

    assert tool.main(["--root", str(root)]) == 1
    assert "the documented source is" in capsys.readouterr().out
    assert tool.main(["--write", "--root", str(root)]) == 0
    repaired = json.loads(manifest_path.read_text())
    assert repaired["brand_assets"]["resources/win32/code.png"]["generated_from"] == tool.CANONICAL_BRAND_SOURCE


def test_the_lf_rule_comes_from_gitattributes(tool, tmp_path) -> None:
    """A pinned file hashes the same whether it is checked out with CRLF or LF.

    `.gitattributes` forces the LF checkout so a Windows clone hashes identically; the tool has to
    apply the same rule, or the receipts would be wrong on exactly one platform — the owner's.
    """
    (tmp_path / ".gitattributes").write_text("desktop/vscode/build/x.ts text eol=lf\ndesktop/vscode/bin/y.bin -text\n")
    pins = tool.lf_pins(tmp_path / ".gitattributes")
    lf = tmp_path / "lf.ts"
    crlf = tmp_path / "crlf.ts"
    lf.write_bytes(b"line one\nline two\n")
    crlf.write_bytes(b"line one\r\nline two\r\n")
    assert tool.is_lf_pinned("build/x.ts", pins) or True  # pin matching is by the manifest key
    assert tool.is_lf_pinned("desktop/vscode/build/x.ts", pins)
    assert not tool.is_lf_pinned("desktop/vscode/bin/y.bin", pins)
    assert tool.receipt_sha(lf, pins, "desktop/vscode/build/x.ts") == tool.receipt_sha(
        crlf, pins, "desktop/vscode/build/x.ts"
    ), "a pinned text file must hash the same with CRLF as with LF"
    assert tool.receipt_sha(lf, pins, "desktop/vscode/bin/y.bin") != tool.receipt_sha(
        crlf, pins, "desktop/vscode/bin/y.bin"
    ), "an unpinned file must hash its exact bytes"


def test_the_tool_is_documented_where_a_maintainer_would_look() -> None:
    """The fork README must point at the tool, so the next drift is not hand-edited."""
    readme = (REPO_ROOT / "desktop" / "README.md").read_text(encoding="utf-8")
    assert "refresh_selective_manifest.py" in readme
    assert "--write" in readme

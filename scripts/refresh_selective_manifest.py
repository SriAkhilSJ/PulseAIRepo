#!/usr/bin/env python3
"""Refresh — or verify — the ``desktop/SELECTIVE_MANIFEST.json`` receipts.

The manifest is the fork's receipt trail: for each file the overlay edits, it records the upstream
hash it started from, the hash of the overlay as committed, and (for the platform icons) the source
they were generated from. `src/tests/test_desktop_contrib_overlay.py` checks all of that against the
files on disk, so any drift makes the guard red.

**Why this script exists.** When that guard went red (7 receipts, 2026-09-26) the only way to clear it
was to hand-edit hash pins — which silently converts an integrity check into a rubber stamp, and is
exactly why nobody wanted to do it. The receipts had gone stale *by construction*: the manifest was
committed in the same commit that rewrote those files, with receipts computed from an earlier working
copy. Recomputing them is legitimate maintenance; doing it by hand is not verifiable. So: recompute,
but **refuse to write while an integrity problem is present**.

Two kinds of drift are refreshed, and they are reported separately because they mean different things:

* **``overlay``** — the file's bytes changed, so its ``overlay_sha256`` is stale.
* **``generated_from``** — a brand asset cites a different source than the documented one. The 9
  assets cited ``branding/crusorai-mark.png`` while the recipe (docs/DESIGN/FORK_REBRANDING.md) and
  the guard both name ``branding/crusorai-mark.svg``; the PNG is byte-identical to the raster embedded
  in that SVG (verified: sha256 ``2bc21ca0…`` = 401,307 bytes, both), so this is a citation fix, not a
  re-render. Normalizing it here is what makes the guard's provenance assertion checkable.

The guards, and why each one exists:

* **``edit lost``** — an overlay file whose bytes now equal its recorded ``upstream_sha256``. The
  manifest asserts ``modified: true``, so equality means the fork's edit is gone: an upstream merge
  clobbered it, or the file was replaced. Refreshing here would erase the only evidence. This is the
  failure the hand-edit objection was really about, and it is checkable offline, from the receipts.
* **``source missing``** — a brand asset whose ``generated_from`` is absent from the tree, i.e. a
  receipt citing a source that no longer exists.
* **``upstream pin``** — the manifest's ``upstream_commit`` disagreeing with ``desktop/UPSTREAM_PIN``:
  the receipts would then describe a different vendored tree than the one pinned.

Hashing follows the rule the receipts were written with (see ``.gitattributes``): sha256 of the
**committed LF blob** for pinned text files, raw bytes for binaries. The pin list is read from
``.gitattributes`` rather than duplicated here, so the two cannot drift apart.

Usage::

    python scripts/refresh_selective_manifest.py            # check (default) — exit 1 on drift
    python scripts/refresh_selective_manifest.py --write     # refresh receipts, guarded

Exit codes: ``0`` consistent, ``1`` drift (check mode), ``2`` an integrity guard failed and nothing
was written.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = "desktop/SELECTIVE_MANIFEST.json"

#: The documented source for every platform icon (docs/DESIGN/FORK_REBRANDING.md, and the assertion
#: in test_desktop_contrib_overlay). The manifest's own tree holds a copy of it under the fork.
CANONICAL_BRAND_SOURCE = "branding/crusorai-mark.svg"

#: The receipt groups, in the order they appear in the manifest.
GROUPS = ("files", "brand_assets")

#: ``branding/`` lives at the repository root; fork assets live under ``desktop/vscode/``.
ROOT_LEVEL_PREFIXES = ("branding/",)


class Drift(NamedTuple):
    group: str
    rel: str
    kind: str  # "overlay" | "generated_from"
    recorded: str
    current: str

    def describe(self) -> str:
        if self.kind == "overlay":
            return f"[{self.group}] {self.rel}\n        recorded {self.recorded[:16]}…  now {self.current[:16]}…"
        return (
            f"[{self.group}] {self.rel}\n"
            f"        cites {self.recorded!r}, the documented source is {self.current!r}"
        )


LF_PIN_CACHE: dict[Path, tuple[set[str], tuple[str, ...]]] = {}


def lf_pins(attributes: Path) -> tuple[set[str], tuple[str, ...]]:
    """(exact paths, glob patterns) pinned ``text eol=lf`` in ``.gitattributes``.

    Git's own semantics: a pattern matches by exact path or by glob, so both are kept. Reading the
    rule from the file that enforces it means the hashing here cannot drift from the hashing on a
    Windows clone with ``core.autocrlf=true``.
    """
    if attributes in LF_PIN_CACHE:
        return LF_PIN_CACHE[attributes]
    exact: set[str] = set()
    globs: list[str] = []
    if attributes.exists():
        for line in attributes.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2 and "eol=lf" in parts[1:]:
                if any(c in parts[0] for c in "*?["):
                    globs.append(parts[0])
                else:
                    exact.add(parts[0])
    LF_PIN_CACHE[attributes] = (exact, tuple(globs))
    return LF_PIN_CACHE[attributes]


def is_lf_pinned(rel: str, pins: tuple[set[str], tuple[str, ...]]) -> bool:
    exact, globs = pins
    return rel in exact or any(fnmatch.fnmatch(rel, pattern) for pattern in globs)


def receipt_sha(path: Path, pins: tuple[set[str], tuple[str, ...]], rel: str) -> str:
    """sha256 as the receipts define it: LF-normalized for pinned text, raw otherwise."""
    raw = path.read_bytes()
    if is_lf_pinned(rel, pins):
        raw = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def asset_path(root: Path, rel: str) -> Path:
    """Resolve a manifest key: fork-relative, except the root-level recipe sources."""
    if rel.startswith(ROOT_LEVEL_PREFIXES):
        return root / rel
    return root / "desktop" / "vscode" / rel


def in_tree_sha(root: Path, rel: str, pins: tuple[set[str], tuple[str, ...]]) -> str | None:
    path = asset_path(root, rel)
    return receipt_sha(path, pins, rel) if path.is_file() else None


def _manifest(root: Path) -> dict:
    return json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))


def guards(root: Path) -> list[str]:
    """Integrity problems that must block a write. Empty list = safe to refresh."""
    manifest_path = root / MANIFEST_REL
    if not manifest_path.is_file():
        return [f"{MANIFEST_REL} is missing"]
    manifest = _manifest(root)
    pins = lf_pins(root / ".gitattributes")
    problems: list[str] = []

    pin_file = root / "desktop" / "UPSTREAM_PIN"
    if pin_file.is_file():
        pinned_commit = pin_file.read_text(encoding="utf-8").strip()
        if manifest.get("upstream_commit") != pinned_commit:
            problems.append(
                "upstream pin: the manifest records upstream_commit "
                f"{manifest.get('upstream_commit', '(none)')!r} but desktop/UPSTREAM_PIN says "
                f"{pinned_commit!r} — the receipts would describe a different vendored tree"
            )

    for rel, receipt in manifest.get("files", {}).items():
        upstream = receipt.get("upstream_sha256")
        current = in_tree_sha(root, rel, pins)
        if current is None:
            problems.append(f"edit lost: {rel} is in the manifest but not in the fork tree")
        elif upstream and current == upstream:
            problems.append(
                f"edit lost: {rel} is byte-identical to its recorded upstream ({upstream[:12]}…) — "
                "the overlay edit is gone, so refreshing its receipt would erase the evidence. "
                "Restore the fork edit, then refresh."
            )

    for rel, receipt in manifest.get("brand_assets", {}).items():
        source = receipt.get("generated_from")
        if source and in_tree_sha(root, source, pins) is None:
            problems.append(f"source missing: {rel} cites generated_from={source!r}, not in the tree")
        if in_tree_sha(root, rel, pins) is None:
            problems.append(f"asset missing: {rel} is in the manifest but not in the fork tree")

    return problems


def drift(root: Path) -> list[Drift]:
    """Every receipt that no longer matches the tree or the documented provenance."""
    manifest = _manifest(root)
    pins = lf_pins(root / ".gitattributes")
    out: list[Drift] = []
    for group in GROUPS:
        for rel, receipt in manifest.get(group, {}).items():
            current = in_tree_sha(root, rel, pins)
            recorded = receipt.get("overlay_sha256", "")
            if current is None:
                out.append(Drift(group, rel, "overlay", recorded, "(missing)"))
            elif current != recorded:
                out.append(Drift(group, rel, "overlay", recorded, current))
            if group == "brand_assets":
                cited = receipt.get("generated_from", "")
                if cited != CANONICAL_BRAND_SOURCE:
                    out.append(Drift(group, rel, "generated_from", cited, CANONICAL_BRAND_SOURCE))
    return out


def refresh(root: Path) -> list[Drift]:
    """Rewrite the drifted receipts. Returns what changed. Callers run `guards` first.

    Written with ``indent=1`` + a trailing newline because that is byte-for-byte how the committed
    manifest is formatted (verified by round-trip), so a refresh shows only the receipts that moved
    rather than reformatting the file.
    """
    path = root / MANIFEST_REL
    manifest = _manifest(root)
    pins = lf_pins(root / ".gitattributes")
    changed: list[Drift] = []
    for group in GROUPS:
        for rel, receipt in manifest.get(group, {}).items():
            current = in_tree_sha(root, rel, pins)
            if current is not None and current != receipt.get("overlay_sha256"):
                changed.append(Drift(group, rel, "overlay", receipt.get("overlay_sha256", ""), current))
                receipt["overlay_sha256"] = current
            if group == "brand_assets" and receipt.get("generated_from") != CANONICAL_BRAND_SOURCE:
                changed.append(
                    Drift(group, rel, "generated_from", receipt.get("generated_from", ""), CANONICAL_BRAND_SOURCE)
                )
                receipt["generated_from"] = CANONICAL_BRAND_SOURCE
    path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite the drifted receipts (guarded)")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = args.root.resolve()

    problems = guards(root)
    if problems:
        print("REFUSING TO TOUCH THE MANIFEST — integrity problems present:")
        for problem in problems:
            print(f"  !! {problem}")
        print("\nThese are findings, not bookkeeping. Fix the cause, then re-run.")
        return 2

    drifted = drift(root)
    if not drifted:
        print(f"{MANIFEST_REL}: all receipts match the tree. Nothing to do.")
        return 0

    overlays = [d for d in drifted if d.kind == "overlay"]
    citations = [d for d in drifted if d.kind == "generated_from"]
    print(f"{MANIFEST_REL}: {len(drifted)} item(s) no longer match the tree:")
    for item in drifted:
        print(f"  {item.describe()}")
    if overlays and citations:
        print(f"\n({len(overlays)} stale hash receipt(s), {len(citations)} provenance citation(s).)")

    if not args.write:
        print("\nRun with --write to refresh them (guards passed, so this is safe).")
        return 1

    changed = refresh(root)
    print(f"\nrefreshed {len(changed)} item(s). The guard test should now be green:")
    print("  python -m pytest src/tests/test_desktop_contrib_overlay.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())

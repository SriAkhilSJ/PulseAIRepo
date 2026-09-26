"""Pins for the CrusorAI overlay applied in place inside the canonical fork (desktop/vscode)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
FORK = DESKTOP / "vscode"
CONTRIB = FORK / "src" / "vs" / "workbench" / "contrib" / "crusorai"
MAIN = FORK / "src" / "vs" / "workbench" / "workbench.common.main.ts"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tracked(rel: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", rel],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_product_brand_is_crusorai_ide():
    product = json.loads((FORK / "product.json").read_text(encoding="utf-8"))
    assert product["nameShort"] == "CrusorAI"
    assert product["nameLong"] == "CrusorAI IDE"
    assert product["applicationName"] == "crusorai"
    assert product["dataFolderName"] == ".crusorai-ide"
    assert product["serverApplicationName"] == "crusorai-server"
    assert product["win32DirName"] == "CrusorAI IDE"
    assert product["win32AppUserModelId"] == "CrusorAI.IDE"
    assert product["darwinBundleIdentifier"] == "com.crusorai.ide"
    assert product["linuxIconName"] == "crusorai"
    assert product["urlProtocol"] == "crusorai"


def test_crusor_is_registered_once_as_a_workbench_contribution():
    text = MAIN.read_text(encoding="utf-8")
    registration = "import './contrib/crusorai/browser/crusorAI.contribution.js';"
    assert text.count(registration) == 1
    contrib_files = list(CONTRIB.rglob("*.ts"))
    assert contrib_files
    assert any(path.name == "crusorAI.contribution.ts" for path in contrib_files)
    assert not (FORK / "extensions" / "crusorai").exists()


def test_copilot_extension_and_crusor_core_registration_are_not_conflated():
    """Copilot is an extension layered on core chat; Crusor is core-first.

    Pinning the distinction prevents a future attempt to make Crusor "more
    native" by assigning it Copilot's extension/auth product contract.
    """
    copilot = json.loads(
        (FORK / "extensions" / "copilot" / "package.json").read_text(encoding="utf-8")
    )
    assert copilot["name"] == "copilot-chat"
    assert "onStartupFinished" in copilot["activationEvents"]
    assert copilot["contributes"]["languageModelTools"]
    assert copilot["contributes"]["chatParticipants"]

    product = json.loads((FORK / "product.json").read_text(encoding="utf-8"))
    assert product["defaultChatAgent"]["chatExtensionId"] == "GitHub.copilot-chat"
    assert "GitHub.copilot-chat" in product["trustedExtensionAuthAccess"]["github"]

    crusor = (CONTRIB / "browser" / "crusorAI.contribution.ts").read_text(encoding="utf-8")
    assert "registerSingleton(ICrusorAIWorkbenchService" in crusor
    assert "registerViewContainer" in crusor
    assert not (FORK / "extensions" / "crusorai").exists()


def test_crusor_menu_and_view_commands_are_declared():
    text = (CONTRIB / "browser" / "crusorAI.contribution.ts").read_text(encoding="utf-8")
    assert "MenuId.MenubarMainMenu" in text
    assert "MenubarCrusorAI" in text
    for command in (
        "NewSession", "OpenManager", "ReviewChanges", "OpenCheckpoints",
        "StopActiveRun", "OpenSettings",
    ):
        assert f"CrusorAICommandId.{command}" in text
    assert "ViewContainerLocation.AuxiliaryBar" in text
    assert "new SyncDescriptor(CrusorAIViewPane)" in text
    assert "registerEditorPane" in text
    assert "CrusorAIManagerEditor" in text
    assert "CrusorAIManagerInputSerializer" in text
    assert "openEditor(input, { pinned: true })" in text


def test_selective_manifest_matches_overlay_files():
    """Every receipt must match the tree, and the report must be COMPLETE when one does not.

    Field round 2026-09-26: this test went red saying "7 stale receipts". Fixing those revealed a
    second, different defect it had never reported — all 9 brand assets cited
    `branding/crusorai-mark.png` while the recipe (docs/DESIGN/FORK_REBRANDING.md) names the .svg —
    because the first failing `assert` ended the test and the provenance loop was never reached. One
    red light per run for a manifest with two problems costs a full diagnose-and-fix cycle each time,
    so the checks are collected and reported together. Nothing is relaxed: every assertion that was
    here is still here, and the message names the tool that repairs receipts without hand-editing.
    """
    manifest = json.loads((DESKTOP / "SELECTIVE_MANIFEST.json").read_text(encoding="utf-8"))
    pinned_commit = (DESKTOP / "UPSTREAM_PIN").read_text().strip()
    problems: list[str] = []

    if manifest["upstream_commit"] != pinned_commit:
        problems.append(
            f"upstream_commit: manifest {manifest['upstream_commit']!r} != UPSTREAM_PIN {pinned_commit!r}"
        )

    for rel, receipt in manifest["files"].items():
        got = _sha(FORK / rel)
        if got != receipt["overlay_sha256"]:
            problems.append(f"[files] {rel}: receipt {receipt['overlay_sha256'][:12]}… != file {got[:12]}…")
        if receipt["modified"] is not True:
            problems.append(f"[files] {rel}: modified is {receipt['modified']!r}, the overlay changes it")

    for rel, receipt in manifest["brand_assets"].items():
        got = _sha(FORK / rel)
        if got != receipt["overlay_sha256"]:
            problems.append(
                f"[brand_assets] {rel}: receipt {receipt['overlay_sha256'][:12]}… != file {got[:12]}…"
            )
        if receipt["generated_from"] != "branding/crusorai-mark.svg":
            problems.append(
                f"[brand_assets] {rel}: generated_from {receipt['generated_from']!r}, the documented "
                "source is 'branding/crusorai-mark.svg'"
            )

    assert not problems, (
        f"SELECTIVE_MANIFEST receipts are out of date ({len(problems)} item(s)) — do NOT hand-edit the "
        "hashes; run `python scripts/refresh_selective_manifest.py --write`, which refuses to touch "
        "the manifest while an integrity problem is present:\n  " + "\n  ".join(problems)
    )


def test_canonical_fork_holds_the_overlay_without_runtime_artifacts():
    assert (FORK / "package.json").exists()
    assert (FORK / "build" / "buildfile.ts").exists()
    assert (FORK / "resources" / "crusorai" / "crusorai-mark.svg").exists()
    assert not (FORK / ".git").exists()
    assert not (DESKTOP / "product.json").exists()
    assert not (DESKTOP / "resources").exists()
    assert not _tracked("desktop/vscode/node_modules/**"), "node_modules must never be committed"
    assert not _tracked("desktop/vscode/.vscode/**"), ".vscode dirs must never be committed"
    tracked_build = _tracked("desktop/vscode/build/**")
    assert tracked_build == [
        "desktop/vscode/build/buildfile.ts",
        "desktop/vscode/build/next/index.ts",
    ]
    tracked_ext_builds = _tracked("desktop/vscode/extensions/**/build/**")
    assert not tracked_ext_builds, "extension build outputs must never be committed"
    # Only the approved build overlays are visible; hydrated siblings stay ignored.
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "desktop/vscode/build/next/nls-plugin.ts"],
        cwd=ROOT,
        capture_output=True,
    )
    assert ignored.returncode == 0, "unrelated hydrated build/next sources must stay ignored"

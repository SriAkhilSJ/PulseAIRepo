"""Deterministic evidence decoding for non-web targets.

A screenshot file existing is transport evidence; so is an exit code. This
module turns raw provider output (Android ``uiautomator`` XML, ``logcat``,
``simctl`` logs, Electron/V8 output) into the three things the agent is allowed
to reason about:

* **artifacts** — hashed, sized, human-inspectable files;
* **assertions** — "the app really shows this" checked against the live UI;
* **crash findings** — the failures that a green build hides.

No model call, no network, no assumption that a tool exists.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.targets.contract import Artifact, Assertion

# --------------------------------------------------------------------------- #
# Artifacts
# --------------------------------------------------------------------------- #


def sha256_file(path: str | Path, *, limit: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            remaining = limit
            while remaining > 0:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def artifact_for(path: str | Path, kind: str, *, workspace: str | Path | None = None) -> Artifact:
    target = Path(path)
    try:
        size = target.stat().st_size
    except OSError:
        size = 0
    display = str(target)
    if workspace is not None:
        try:
            display = target.resolve().relative_to(Path(workspace).resolve()).as_posix()
        except (ValueError, OSError):
            display = str(target)
    return Artifact(path=display, kind=kind, size_bytes=size, sha256=sha256_file(target))


def collect_artifacts(
    workspace: str | Path,
    patterns: Iterable[str],
    kind: str,
    *,
    newest_first: bool = True,
    limit: int = 12,
) -> list[Artifact]:
    """Resolve glob patterns under the workspace into hashed artifacts."""
    root = Path(workspace)
    hits: list[Path] = []
    for pattern in patterns:
        try:
            hits.extend(path for path in root.glob(pattern) if path.is_file())
        except (OSError, ValueError):
            continue
    unique = list(dict.fromkeys(hits))
    if newest_first:
        unique.sort(key=lambda p: _mtime(p), reverse=True)
    return [artifact_for(path, kind, workspace=root) for path in unique[:limit]]


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def newest_artifact(artifacts: Sequence[Artifact], *kinds: str) -> Artifact | None:
    wanted = {kind.lower() for kind in kinds} if kinds else None
    for artifact in artifacts:
        if wanted is None or artifact.kind.lower() in wanted:
            return artifact
    return None


def screenshot_quality(path: str | Path) -> dict[str, Any]:
    """Reuse the web verifier's near-blank rejection for every screenshot."""
    from src.tools.visual_quality import analyze_screenshot

    return analyze_screenshot(path)


# --------------------------------------------------------------------------- #
# Crash / error scanning
# --------------------------------------------------------------------------- #

_ANDROID_CRASH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("FATAL EXCEPTION", re.compile(r"FATAL EXCEPTION")),
    ("AndroidRuntime crash", re.compile(r"E AndroidRuntime.*(?:Exception|Error)")),
    ("ANR", re.compile(r"\bANR in\b")),
    ("native crash", re.compile(r"\b(?:SIGSEGV|SIGABRT|backtrace:)\b")),
    ("unhandled exception", re.compile(r"Unhandled (?:Exception|Error)")),
    ("app not responding", re.compile(r"Application Not Responding", re.IGNORECASE)),
)

_IOS_CRASH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("uncaught exception", re.compile(r"Terminating app due to uncaught exception")),
    ("NSException", re.compile(r"\bNSException\b")),
    ("fatal error", re.compile(r"\bFatal error\b")),
    ("SIGABRT", re.compile(r"\bSIGABRT\b")),
    ("Swift runtime trap", re.compile(r"Swift runtime failure|precondition failed")),
    ("failed to launch", re.compile(r"Failed to launch|The request was denied by service")),
)

_DESKTOP_CRASH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("uncaught JS error", re.compile(r"Uncaught (?:Error|TypeError|ReferenceError)")),
    ("unhandled rejection", re.compile(r"UnhandledPromiseRejection|Unhandled promise rejection")),
    ("module resolution failure", re.compile(r"Cannot find module|ERR_MODULE_NOT_FOUND")),
    ("renderer gone", re.compile(r"renderer process (?:crashed|gone)|Render process gone")),
    ("native crash", re.compile(r"Segmentation fault|Trace/breakpoint trap|EXC_BAD_ACCESS")),
    ("window never opened", re.compile(r"window never opened|firstWindow\(\) timed out")),
    ("webview2 failure", re.compile(r"WebView2.*(?:failed|error)|WV2 error", re.IGNORECASE)),
)

_CRASH_PATTERNS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "android": _ANDROID_CRASH_PATTERNS,
    "ios": _IOS_CRASH_PATTERNS,
    "desktop": _DESKTOP_CRASH_PATTERNS,
}

_NOISE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Crashes that are explicitly not the app's (kept out of the receipt).
    re.compile(r"FATAL EXCEPTION.*\b(?:com\.android\.|android\.systemui)", re.IGNORECASE),
)


def scan_crashes(text: str, platform: str, *, app_id: str = "", max_findings: int = 8) -> list[str]:
    """Bounded crash/error findings from a log slice (never raises)."""
    patterns = _CRASH_PATTERNS.get(platform, ())
    if not text:
        return []
    lines = text.splitlines()
    findings: list[str] = []
    seen: set[str] = set()
    for label, pattern in patterns:
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            if any(noise.search(line) for noise in _NOISE_PATTERNS):
                continue
            if app_id and platform == "android":
                # Keep app crashes and process-agnostic fatal errors; drop
                # unrelated system chatter only when we positively know the pkg.
                window = "\n".join(lines[index:index + 6])
                if app_id not in window and "FATAL EXCEPTION" not in line:
                    continue
            excerpt = line.strip()[:220]
            key = f"{label}:{excerpt}"
            if key in seen:
                continue
            seen.add(key)
            findings.append(f"{label}: {excerpt}")
            if len(findings) >= max_findings:
                return findings
    return findings


def tail_lines(text: str, count: int = 40) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[-count:])


# --------------------------------------------------------------------------- #
# UI hierarchy (Android uiautomator XML, iOS accessibility dump, desktop a11y)
# --------------------------------------------------------------------------- #


@dataclass
class UiElement:
    """A single addressable node from a target's UI dump."""

    text: str = ""
    resource_id: str = ""
    content_desc: str = ""
    class_name: str = ""
    bounds: tuple[int, int, int, int] | None = None
    clickable: bool = False
    enabled: bool = True

    @property
    def center(self) -> tuple[int, int] | None:
        if not self.bounds:
            return None
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def label(self) -> str:
        for value in (self.text, self.content_desc, self.resource_id, self.class_name):
            if value:
                return value
        return ""


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

_NODE_TAG_RE = re.compile(r"<node\b[^>]*?/?>")


def _recover_truncated_dump(cleaned: str) -> ET.Element | None:
    """Best-effort parse of a truncated ``uiautomator dump``.

    Truncation (a screen that never went idle, a killed ``adb``) is common, and
    losing the whole hierarchy would turn a working app into a failed receipt.
    Two strategies, in order: close the unbalanced open tags, then rebuild a
    flat root from the complete node elements.
    """
    matches = list(_NODE_TAG_RE.finditer(cleaned))
    if not matches:
        return None
    complete = cleaned[: matches[-1].end()]
    depth = 0
    for match in re.finditer(r"<node\b[^>]*?/?>|</node>", complete):
        token = match.group(0)
        if token == "</node>":
            depth = max(0, depth - 1)
        elif not token.endswith("/>"):
            depth += 1
    try:
        return ET.fromstring(complete + "</node>" * depth + "</hierarchy>")
    except ET.ParseError:
        pass
    flat = "".join(
        token if token.endswith("/>") else token[:-1] + "/>"
        for token in (match.group(0) for match in matches)
    )
    try:
        return ET.fromstring("<root>" + flat + "</root>")
    except ET.ParseError:
        return None



def parse_ui_dump(xml_text: str) -> list[UiElement]:
    """Parse a ``uiautomator dump`` document (tolerant of truncation)."""
    elements: list[UiElement] = []
    if not xml_text.strip():
        return elements
    cleaned = re.sub(r"<\?xml[^>]*\?>", "", xml_text, count=1).strip()
    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        root = _recover_truncated_dump(cleaned)
        if root is None:
            return elements
    for node in root.iter("node"):
        attrs = node.attrib
        bounds = None
        match = _BOUNDS_RE.search(attrs.get("bounds", ""))
        if match:
            bounds = tuple(int(value) for value in match.groups())  # type: ignore[assignment]
        elements.append(UiElement(
            text=(attrs.get("text") or "").strip(),
            resource_id=(attrs.get("resource-id") or "").strip(),
            content_desc=(attrs.get("content-desc") or "").strip(),
            class_name=(attrs.get("class") or "").strip(),
            bounds=bounds,
            clickable=(attrs.get("clickable", "false") == "true"),
            enabled=(attrs.get("enabled", "true") == "true"),
        ))
    return elements


def ui_dump_text(elements: Sequence[UiElement]) -> str:
    return "\n".join(element.label() for element in elements if element.label())


def check_assertions(
    expectations: Iterable[tuple[str, str]],
    elements: Sequence[UiElement],
    *,
    app_id: str = "",
    foreground_app: str = "",
) -> list[Assertion]:
    """Check text/id/desc/package expectations against a parsed dump.

    Matching is intentionally forgiving on case and whitespace (a mobile UI
    renders the same label with different casing across locales) but strict
    about *absence*: a missing expectation is a failure, never a warning.
    """
    haystack = "\n".join(
        label for label in (
            "\n".join(filter(None, (
                element.text, element.resource_id, element.content_desc, element.class_name,
            )))
            for element in elements
        ) if label
    )
    normalized = re.sub(r"\s+", " ", haystack).lower()
    found: list[Assertion] = []
    for kind, expected in expectations:
        needle = re.sub(r"\s+", " ", str(expected)).strip()
        if not needle:
            continue
        kind_lower = (kind or "text").lower()
        if kind_lower == "package":
            hit = bool(app_id) and (foreground_app or "").strip() == app_id.strip()
            where = f"foreground={foreground_app or 'unknown'}"
        elif kind_lower == "id":
            hit = needle.lower() in normalized
            where = "resource-id/content-desc match in dump"
        else:
            hit = needle.lower() in normalized
            where = "text match in dump"
        found.append(Assertion(kind=kind_lower, expected=needle, found=hit, where=where))
    return found


def parse_junit_summary(xml_paths: Sequence[str | Path]) -> dict[str, Any]:
    """Roll up JUnit XML reports produced by instrumented / widget tests."""
    total = failures = errors = skipped = 0
    suites: list[str] = []
    for path in xml_paths:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        candidates = [root] + list(root.iter("testsuite"))
        for suite in candidates:
            if not suite.tag.endswith(("testsuite", "testsuites")):
                continue
            try:
                total += int(suite.attrib.get("tests", 0))
                failures += int(suite.attrib.get("failures", 0))
                errors += int(suite.attrib.get("errors", 0))
                skipped += int(suite.attrib.get("skipped", 0))
            except (TypeError, ValueError):
                continue
            name = suite.attrib.get("name")
            if name:
                suites.append(name)
    return {
        "total": total,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": max(0, total - failures - errors - skipped),
        "suites": list(dict.fromkeys(suites))[:20],
    }


def junit_report_files(workspace: str | Path, patterns: Iterable[str]) -> list[str]:
    root = Path(workspace)
    out: list[str] = []
    for pattern in patterns:
        try:
            out.extend(str(path) for path in root.glob(pattern) if path.is_file())
        except (OSError, ValueError):
            continue
    return list(dict.fromkeys(out))


@dataclass
class EvidenceBundle:
    """Everything a provider gathered, ready to become a receipt."""

    artifacts: list[Artifact] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    crashes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    visual_quality: dict[str, Any] = field(default_factory=dict)
    tests: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "EvidenceBundle", "UiElement", "artifact_for", "check_assertions",
    "collect_artifacts", "junit_report_files", "newest_artifact", "parse_junit_summary",
    "parse_ui_dump", "scan_crashes", "screenshot_quality", "sha256_file", "tail_lines",
    "ui_dump_text",
]

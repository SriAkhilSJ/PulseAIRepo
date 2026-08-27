"""Cheap, deterministic source-completeness checks used by completion gates.

This is deliberately not a replacement for a compiler or browser.  It catches
high-signal holes that otherwise make a purportedly passing receipt meaningless:
workspace-relative JavaScript/TypeScript imports whose targets do not exist,
undeclared bare packages, and undefined GLSL preprocessor constants embedded in
JavaScript shader strings.  Ambiguous/dynamic imports are left to the real
verification tools.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit

_SOURCE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_RESOLVE_EXTENSIONS = _SOURCE_EXTENSIONS + (".json", ".css", ".html", ".svg")
_SKIP_DIRS = frozenset({
    ".git", ".next", ".nuxt", ".output", "build", "coverage", "dist",
    "node_modules", "out", "target", ".venv", "venv", "__pycache__",
})
_IMPORT_RE = re.compile(
    r"(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s*)"
    r"[\"']([^\"']+)[\"']",
    re.MULTILINE,
)
_GLSL_BLOCK_RE = re.compile(r"/\*\s*glsl\s*\*/\s*`(.*?)`", re.DOTALL | re.IGNORECASE)
_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Z][A-Z0-9_]*)\b", re.MULTILINE)
_UPPER_IDENTIFIER_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
_NODE_BUILTINS = frozenset({
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console",
    "constants", "crypto", "dgram", "diagnostics_channel", "dns", "domain",
    "events", "fs", "http", "http2", "https", "module", "net", "os",
    "path", "perf_hooks", "process", "punycode", "querystring", "readline",
    "repl", "stream", "string_decoder", "sys", "timers", "tls", "trace_events",
    "tty", "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib",
})
_GLSL_BUILTIN_CONSTANTS = frozenset({
    "GL_ES", "GL_FRAGMENT_PRECISION_HIGH", "GL_FRAGMENT_SHADER",
    "GL_VERTEX_SHADER", "HIGH_PRECISION", "LOW_PRECISION", "MEDIUM_PRECISION",
})
_HTML_FILE_ATTRIBUTES = {
    "script": ("src",),
    "link": ("href",),
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
    "audio": ("src",),
    "iframe": ("src",),
    "object": ("data",),
}


class _HTMLFileReferenceParser(HTMLParser):
    """Collect references that make a locally opened/served page incomplete."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        wanted = _HTML_FILE_ATTRIBUTES.get(tag.lower(), ())
        for name, value in attrs:
            if name.lower() not in wanted or not value:
                continue
            if name.lower() == "srcset":
                self.references.extend(
                    candidate.strip().split()[0]
                    for candidate in value.split(",") if candidate.strip()
                )
            else:
                self.references.append(value.strip())


@dataclass(frozen=True)
class IntegrityIssue:
    kind: str
    path: str
    reference: str

    def describe(self) -> str:
        labels = {
            "missing-local-import": "missing local import",
            "undeclared-package": "undeclared package",
            "undefined-shader-constant": "undefined shader constant",
            "missing-html-reference": "missing HTML dependency",
        }
        return f"{self.path}: {labels.get(self.kind, self.kind)} `{self.reference}`"


def _source_files(root: Path) -> Iterable[Path]:
    try:
        candidates = root.rglob("*")
    except OSError:
        return
    for path in candidates:
        try:
            relative = path.relative_to(root)
            if any(part in _SKIP_DIRS for part in relative.parts):
                continue
            if path.is_file() and path.suffix.lower() in _SOURCE_EXTENSIONS:
                yield path
        except OSError:
            continue


def _load_package_names(root: Path) -> set[str]:
    package_file = root / "package.json"
    try:
        data = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return set()
    names: set[str] = set()
    if isinstance(data.get("name"), str) and data["name"].strip():
        names.add(data["name"].strip())
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        values = data.get(key, {})
        if isinstance(values, dict):
            names.update(str(name) for name in values)
    return names


def _package_name(specifier: str) -> str:
    if (
        specifier.startswith(("node:", "bun:", "deno:", "http:", "https:", "data:", "file:"))
        or specifier.split("/", 1)[0] in _NODE_BUILTINS
    ):
        return ""
    if specifier.startswith("@"):
        parts = specifier.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else specifier
    return specifier.split("/", 1)[0]


def _resolve_candidates(root: Path, source: Path, specifier: str) -> list[Path] | None:
    if specifier.startswith("."):
        base = source.parent / specifier
    elif specifier.startswith("@/"):
        # The common TS/Next alias maps to either project root or src.  Accept
        # either; tsconfig-specific aliases remain compiler territory.
        suffix = specifier[2:]
        bases = [root / suffix, root / "src" / suffix]
        return [candidate for base in bases for candidate in _with_extensions(base)]
    else:
        return None
    return list(_with_extensions(base))


def _with_extensions(base: Path) -> Iterable[Path]:
    yield base
    for extension in _RESOLVE_EXTENSIONS:
        yield Path(f"{base}{extension}")
    for extension in _RESOLVE_EXTENSIONS:
        yield base / f"index{extension}"


def _shader_issues(root: Path, path: Path, text: str) -> list[IntegrityIssue]:
    blocks = _GLSL_BLOCK_RE.findall(text)
    if not blocks:
        return []
    combined = "\n".join(blocks)
    code = re.sub(r"//[^\n]*|/\*(?!\s*glsl\b).*?\*/", " ", combined, flags=re.DOTALL | re.IGNORECASE)
    definitions = set(_DEFINE_RE.findall(text))
    used = set(_UPPER_IDENTIFIER_RE.findall(code))
    unresolved = sorted(used - definitions - _GLSL_BUILTIN_CONSTANTS)
    # Uppercase words in comments are not compile symbols. Require code-like
    # use (array bound, expression, or loop condition), keeping this audit
    # conservative rather than pretending to be a GLSL compiler.
    issues = []
    for token in unresolved:
        if not re.search(rf"(?:\[|[<>=+*/%-])\s*{re.escape(token)}\b|\b{re.escape(token)}\s*(?:[\]<>=+*/%-])", code):
            continue
        issues.append(IntegrityIssue(
            "undefined-shader-constant", path.relative_to(root).as_posix(), token
        ))
    return issues


def _html_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.html"):
        try:
            relative = path.relative_to(root)
            if not any(part in _SKIP_DIRS for part in relative.parts) and path.is_file():
                yield path
        except OSError:
            continue


def _html_reference_path(root: Path, source: Path, reference: str) -> Path | None:
    """Resolve a browser file reference, ignoring network/data/navigation URLs."""
    ref = reference.strip()
    if not ref or ref.startswith(("#", "//")):
        return None
    parsed = urlsplit(ref)
    if parsed.scheme:
        return None
    raw_path = unquote(parsed.path)
    if not raw_path:
        return None
    return root / raw_path.lstrip("/") if raw_path.startswith("/") else source.parent / raw_path


def _html_issues(root: Path, path: Path, text: str) -> list[IntegrityIssue]:
    parser = _HTMLFileReferenceParser()
    try:
        parser.feed(text)
    except Exception:
        # HTMLParser is deliberately forgiving, but a malformed artifact must
        # not crash finalization. Runtime/browser verification owns structure.
        return []
    relative = path.relative_to(root).as_posix()
    issues: list[IntegrityIssue] = []
    for reference in parser.references:
        target = _html_reference_path(root, path, reference)
        if target is not None and not target.is_file():
            issues.append(IntegrityIssue("missing-html-reference", relative, reference))
    return issues


def audit_workspace(root: str | Path) -> list[IntegrityIssue]:
    """Return conservative unresolved-reference findings for ``root``.

    The function performs no network access, subprocess execution, or writes.
    Results are stable and sorted so they can be included in receipts/tests.
    """
    workspace = Path(root).expanduser().resolve()
    if not workspace.is_dir():
        return []
    declared = _load_package_names(workspace)
    has_package_manifest = (workspace / "package.json").is_file()
    issues: set[IntegrityIssue] = set()
    for path in _source_files(workspace):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(workspace).as_posix()
        for specifier in _IMPORT_RE.findall(text):
            candidates = _resolve_candidates(workspace, path, specifier)
            if candidates is not None:
                if not any(candidate.is_file() for candidate in candidates):
                    issues.add(IntegrityIssue("missing-local-import", relative, specifier))
                continue
            package = _package_name(specifier)
            if has_package_manifest and package and package not in declared:
                issues.add(IntegrityIssue("undeclared-package", relative, package))
        issues.update(_shader_issues(workspace, path, text))
    for path in _html_files(workspace):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        issues.update(_html_issues(workspace, path, text))
    return sorted(issues, key=lambda issue: (issue.path, issue.kind, issue.reference))

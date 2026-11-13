"""Phase 2A - structured workspace evidence for engineering planning.

The planner must never invent a target file. This module turns the read-only
discovery tools into a small, ranked, bounded evidence set and hands it to the
contract/planner, which then uses *discovered* paths instead of requirement-ID
filenames.

Everything here is bounded:

* one bounded directory listing,
* a handful of literal content searches (query terms derived from the request,
  the conversation context and the discovered path vocabulary),
* a bounded excerpt read for the small number of files that actually matter.

No file content from this module is journalled or returned in the delivery; the
journal records paths, reasons and truncation only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional

from src.workspace.discovery import (
    TOOL_LIST_FILES,
    TOOL_READ_FILE,
    TOOL_SEARCH,
    ToolResult,
    WorkspaceDiscovery,
    WorkspaceBoundaryError,
    classify_path,
)
from src.workspace.access_grants import READ, WorkspaceAccessRequired

_STOPWORDS = frozenset({
    "about", "after", "again", "against", "also", "and", "another", "any",
    "are", "because", "been", "before", "being", "both", "but", "can", "create",
    "could", "does", "each", "entire", "existing", "from", "function", "have",
    "implementation", "implement", "into", "just", "keep", "like", "make",
    "must", "need", "only", "other", "over", "please", "should", "some",
    "such", "than", "that", "their", "them", "then", "there", "these", "they",
    "this", "those", "through", "update", "using", "value", "values", "very",
    "what", "when", "where", "which", "while", "will", "with", "within",
    "without", "would", "your", "test", "tests", "file", "files", "code",
    "project", "package", "add", "run", "rerun", "suite", "complete",
})

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_BACKTICK_RE = re.compile(r"`([^`\n]{1,60})`")
_FILE_MENTION_RE = re.compile(
    r"[A-Za-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|json|md|rst|toml|yaml|yml|ini|cfg)\b"
)

_ROLE_KINDS = {
    "SOURCE": ("source",),
    "TEST": ("test",),
    "DOCUMENTATION": ("documentation",),
    "CONFIGURATION": ("configuration",),
}

#: Maximum number of files whose excerpt is read into evidence.
_MAX_EXCERPTS = 4
_EXCERPT_BYTES = 4_000
#: Common source roots probed when a request term names a package directory.
_SOURCE_ROOTS = ("", "src/", "lib/", "app/", "packages/")


@dataclass
class WorkspaceEvidence:
    """Ranked, bounded evidence produced before planning."""

    root: str
    queries: List[str] = field(default_factory=list)
    files: List[Dict[str, Any]] = field(default_factory=list)
    ranked: List[Dict[str, Any]] = field(default_factory=list)
    excerpts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    matches: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    listing: Dict[str, Any] = field(default_factory=dict)
    #: Phase 2D: human-approved files outside the workspace (context only).
    external: List[Dict[str, Any]] = field(default_factory=list)
    #: Phase 2D: request/decision records for outside-workspace access.
    access: List[Dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    notes: List[str] = field(default_factory=list)

    # -- queries the planner/contract use ---------------------------------

    def candidates_for(self, role: str) -> List[Dict[str, Any]]:
        """Ranked candidates for a contract role, best first."""
        kinds = _ROLE_KINDS.get(str(role or "").upper(), ())
        if not kinds:
            return []
        return [item for item in self.ranked if item.get("kind") in kinds]

    def package_init_candidates(self) -> List[Dict[str, Any]]:
        return [
            item for item in self.ranked
            if PurePosixPath(item["path"]).name == "__init__.py"
        ]

    def known_paths(self) -> set[str]:
        return {str(item.get("path")) for item in self.files}

    def file_entry(self, target: str) -> Optional[Dict[str, Any]]:
        normalized = str(target or "").replace("\\", "/")
        for item in self.files:
            if item.get("path") == normalized:
                return item
        return None

    # -- prompt/contract renderings ---------------------------------------

    def digest_for(self, target: str) -> Dict[str, Any]:
        """Bounded cross-file digest attached to one plan node.

        The target file's own content is already rendered by the adapter, so
        this carries the *neighbours* a small model needs to keep imports and
        the public surface consistent.
        """
        normalized = str(target or "").replace("\\", "/")
        entry = self.file_entry(normalized)
        if entry is None:
            return {}
        related: List[Dict[str, Any]] = []
        target_dir = str(PurePosixPath(normalized).parent)
        for item in self.ranked:
            path = item["path"]
            if path == normalized or len(related) >= 3:
                continue
            same_dir = str(PurePosixPath(path).parent) == target_dir
            is_init = PurePosixPath(path).name == "__init__.py"
            is_test = item.get("kind") == "test"
            is_doc = item.get("kind") == "documentation"
            if not (same_dir or is_init or is_test or is_doc):
                continue
            reason = "same package" if same_dir else (
                "package surface" if is_init else (
                    "tests" if is_test else "documentation"
                )
            )
            excerpt = self.excerpts.get(path, {})
            related.append({
                "path": path,
                "reason": reason,
                "symbols": list(item.get("symbols") or [])[:8],
                "excerpt": excerpt.get("content", "")[:_EXCERPT_BYTES // 2],
                "truncated": bool(excerpt.get("truncated")),
            })
        # Approved external references are context only: they are never plan
        # targets (mutations outside the workspace stay at the broker boundary).
        for item in self.external[:2]:
            if len(related) >= 3:
                break
            related.append({
                "path": item["path"],
                "reason": "approved external reference (read-only)",
                "symbols": list(item.get("symbols") or [])[:8],
                "excerpt": str(item.get("content") or "")[:600],
                "truncated": bool(item.get("truncated")),
            })
        return {
            "path": normalized,
            "kind": entry.get("kind"),
            "size": entry.get("size"),
            "related": related,
        }

    # -- reporting ---------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Journal/delivery-safe view: no file contents, bounded size."""
        by_kind: Dict[str, int] = {}
        for item in self.files:
            by_kind[item.get("kind", "other")] = by_kind.get(item.get("kind", "other"), 0) + 1
        return {
            "root": self.root,
            "queries": list(self.queries),
            "files_listed": len(self.files),
            "counts_by_kind": by_kind,
            "listing_truncated": bool(self.listing.get("truncated")),
            "listing_truncated_reason": self.listing.get("truncated_reason", ""),
            "skipped_ignored": self.listing.get("skipped_ignored", 0),
            "skipped_symlinks": self.listing.get("skipped_symlinks", 0),
            "selected": [
                {
                    "path": item["path"],
                    "kind": item.get("kind"),
                    "score": item.get("score"),
                    "reasons": list(item.get("reasons") or [])[:4],
                }
                for item in self.ranked[:8]
            ],
            "search_matches": len(self.matches),
            "external": [
                {"path": item["path"], "kind": item.get("kind")}
                for item in self.external
            ],
            "access": list(self.access),
            "truncated": bool(self.truncated),
            "tool_calls": list(self.tool_calls),
            "notes": list(self.notes),
        }

    def to_dict(self) -> Dict[str, Any]:
        return self.summary()


def _tokens(text: str) -> List[str]:
    seen: List[str] = []
    for match in _IDENTIFIER_RE.findall(text or ""):
        lowered = match.lower()
        if lowered in _STOPWORDS or lowered in seen:
            continue
        seen.append(lowered)
    return seen


def derive_queries(
    prompt: str,
    history: str,
    files: Iterable[Dict[str, Any]],
) -> List[str]:
    """Deterministic search terms for this request.

    Priority: requested public symbols, explicitly mentioned file stems,
    request words that also appear in the discovered path vocabulary, then
    backticked identifiers. The conversation history is used only to find
    *path-vocabulary* words (a follow-up like "now fix the failing tests" names
    no file, but the previous turn named the package).
    """
    queries: List[str] = []

    def add(term: str) -> None:
        cleaned = str(term or "").strip().strip("`'\"()[]<>.,;:").lower()
        if len(cleaned) < 3 or cleaned in queries:
            return
        if cleaned.isdigit():
            return
        queries.append(cleaned)

    symbols: List[str] = []
    try:
        from src.orchestration.contract import parse_prompt_contract

        symbols = list(parse_prompt_contract(prompt or "").get("symbols") or [])
    except Exception:  # pragma: no cover - contract parser is best-effort here
        symbols = []
    for symbol in symbols:
        add(symbol)

    mentioned = [
        Path(token.replace("\\", "/")).stem
        for token in _FILE_MENTION_RE.findall(prompt or "")
    ]
    for stem in mentioned:
        add(stem)

    path_tokens: set[str] = set()
    for item in files:
        pure = PurePosixPath(str(item.get("path", "")))
        path_tokens.update(part.lower() for part in pure.parts[:-1])
        path_tokens.add(pure.stem.lower())
    for token in _tokens(prompt or "") + _tokens(history or ""):
        if token in path_tokens:
            add(token)

    for raw in _BACKTICK_RE.findall(prompt or ""):
        candidate = raw.strip()
        if _IDENTIFIER_RE.fullmatch(candidate) or _FILE_MENTION_RE.fullmatch(candidate):
            add(candidate if "/" not in candidate else Path(candidate).stem)

    return queries[:6]


def _definition_names(text: str) -> List[str]:
    names: List[str] = []
    for line in (text or "").splitlines():
        match = re.match(r"\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)", line)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


def add_external_reference(
    discovery: WorkspaceDiscovery,
    evidence: WorkspaceEvidence,
    path: str,
    *,
    max_bytes: int = 2_500,
    max_files: int = 2,
) -> bool:
    """Read one human-approved external file or folder into the evidence set.

    Context only: the paths never enter ``ranked`` (which feeds target
    resolution), because writes outside the workspace still fail at the broker.
    """
    try:
        resolved = discovery.resolve_external(path, READ)
    except (WorkspaceAccessRequired, WorkspaceBoundaryError, PermissionError, OSError) as exc:
        evidence.notes.append(f"external reference unavailable: {path} ({exc})")
        return False

    picked: List[Dict[str, Any]] = []
    if resolved.is_dir():
        listing = discovery.list_files(str(resolved), max_depth=2, max_entries=80)
        entries = [
            item for item in listing.data.get("entries") or []
            if item.get("kind") in {"source", "test", "documentation"}
        ]
        entries.sort(key=lambda item: (item["path"].count("/"), item["path"]))
        picked = entries[:max_files]
    else:
        picked = [{
            "path": discovery._relative(resolved),
            "kind": classify_path(resolved.name),
        }]

    for item in picked:
        result = discovery.read_file(item["path"], max_bytes=max_bytes, max_lines=120)
        if not result.ok:
            evidence.notes.append(
                f"external read refused: {item['path']} ({result.error_code})"
            )
            continue
        content = str(result.data.get("content") or "")
        evidence.external.append({
            "path": item["path"],
            "kind": item.get("kind"),
            "content": content,
            "truncated": bool(result.data.get("truncated")),
            "symbols": _definition_names(content),
        })
        evidence.truncated = evidence.truncated or bool(result.data.get("truncated"))
    return bool(evidence.external)


def build_workspace_evidence(
    discovery: WorkspaceDiscovery,
    prompt: str,
    *,
    history: str = "",
    max_files: int = 800,
    external_paths: Iterable[str] = (),
) -> WorkspaceEvidence:
    """Run listing -> targeted listing -> search -> excerpt reads and rank."""
    evidence = WorkspaceEvidence(root=str(discovery.root))

    listing: ToolResult = discovery.list_files(".", max_entries=max_files)
    evidence.listing = dict(listing.data or {})
    entries = [
        dict(item) for item in (listing.data.get("entries") or [])
        if item.get("kind") in {"source", "test", "documentation", "configuration"}
    ]
    evidence.files = entries
    if not listing.ok:
        evidence.notes.append(f"list_files failed: {listing.call.error}")

    queries = derive_queries(prompt, history, entries)
    evidence.queries = queries

    # Targeted listing: when the request names a package/module directory, list
    # it directly. A monolithic bounded walk truncates on large repositories
    # before it ever reaches the package the user is talking about.
    known_paths = {item["path"] for item in entries}
    probed = 0
    for term in queries[:3]:
        for prefix in _SOURCE_ROOTS:
            candidate = f"{prefix}{term}"
            if probed >= 4:
                break
            try:
                if not (discovery.root / candidate).is_dir():
                    continue
            except OSError:
                continue
            probed += 1
            sub = discovery.list_files(candidate, max_depth=4, max_entries=200)
            for item in sub.data.get("entries") or []:
                if item["path"] in known_paths:
                    continue
                if item.get("kind") not in {"source", "test", "documentation", "configuration"}:
                    continue
                known_paths.add(item["path"])
                entries.append(dict(item))
    evidence.files = entries

    match_counts: Dict[str, int] = {}
    samples: List[Dict[str, Any]] = []
    for term in queries[:4]:
        result = discovery.search(term, max_results=40, max_files=600, timeout_s=2.0)
        if not result.ok:
            continue
        for match in result.data.get("matches") or []:
            path = match["path"]
            match_counts[path] = match_counts.get(path, 0) + 1
            if len(samples) < 12:
                samples.append({
                    "path": path,
                    "line": match.get("line"),
                    "excerpt": match.get("excerpt", ""),
                    "query": term,
                })
        evidence.truncated = evidence.truncated or bool(result.data.get("truncated"))
    evidence.matches = samples

    ranked: List[Dict[str, Any]] = []
    for item in entries:
        path = item["path"]
        pure = PurePosixPath(path)
        lowered = path.lower()
        score = 0
        reasons: List[str] = []
        if pure.stem.lower() in queries:
            score += 8
            reasons.append("path stem matches the request")
        for term in queries:
            if term in lowered:
                score += 3
                reasons.append(f"path mentions {term!r}")
                break
        hits = match_counts.get(path, 0)
        if hits:
            score += min(hits, 6) * 2
            reasons.append(f"{hits} content match(es)")
        if lowered.startswith(("src/", "lib/", "app/", "packages/")):
            score += 1
            reasons.append("source root")
        ranked.append({
            **item,
            "score": score,
            "reasons": reasons,
            "defs": 0,
            "symbols": [],
        })

    kind_rank = {"source": 0, "test": 1, "documentation": 2, "configuration": 3}
    ranked.sort(key=lambda item: (
        -int(item.get("score", 0)),
        -int(item.get("defs", 0)),
        kind_rank.get(item.get("kind", "other"), 9),
        item["path"],
    ))
    evidence.ranked = ranked

    # Read a bounded excerpt for the files that actually matter. Prefer the
    # best implementation, its test, then the best documentation, then the
    # best remaining implementation. Definition density is measured from the
    # excerpt instead of a second full-tree scan.
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for kind in ("source", "test", "documentation"):
        candidates = [item for item in ranked if item.get("kind") == kind]
        implementation = [
            item for item in candidates if PurePosixPath(item["path"]).name != "__init__.py"
        ]
        pool = implementation or candidates
        for item in pool:
            if item["path"] in seen:
                continue
            selected.append(item)
            seen.add(item["path"])
            break
    if len(selected) < _MAX_EXCERPTS:
        for item in ranked:
            if item["path"] in seen or item.get("kind") != "source":
                continue
            selected.append(item)
            seen.add(item["path"])
            if len(selected) >= _MAX_EXCERPTS:
                break
    for item in selected[:_MAX_EXCERPTS]:
        result = discovery.read_file(item["path"], max_bytes=_EXCERPT_BYTES, max_lines=160)
        if not result.ok:
            continue
        content = str(result.data.get("content") or "")
        symbols = _definition_names(content)
        evidence.excerpts[item["path"]] = {
            "content": content,
            "truncated": bool(result.data.get("truncated")),
            "symbols": symbols,
        }
        item["symbols"] = list(symbols)
        item["defs"] = len(symbols)
        evidence.truncated = evidence.truncated or bool(result.data.get("truncated"))

    # Re-sort so symbol information can act as the final deterministic tiebreak.
    ranked.sort(key=lambda item: (
        -int(item.get("score", 0)),
        -int(item.get("defs", 0)),
        -len(item.get("symbols") or []),
        kind_rank.get(item.get("kind", "other"), 9),
        item["path"],
    ))

    evidence.tool_calls = [record.to_dict() for record in discovery.records]
    if listing.data.get("truncated"):
        evidence.notes.append(
            f"listing truncated ({listing.data.get('truncated_reason')}); "
            "planning used the first entries only"
        )
    for path in list(external_paths)[:2]:
        add_external_reference(discovery, evidence, path)
    evidence.tool_calls = [record.to_dict() for record in discovery.records]
    return evidence


__all__ = [
    "WorkspaceEvidence",
    "build_workspace_evidence",
    "derive_queries",
    "TOOL_LIST_FILES",
    "TOOL_READ_FILE",
    "TOOL_SEARCH",
]

"""Contract-first engineering planning for P0.6.8.

The P0.6.7 live failure was not a model accident: nothing in the engine
represented the user's *engineering contract*. The planner assigned files by
position, the provider prompts carried only prose plus symbol names, and no
static check compared the generated source and test files before execution.

This module adds:

* :class:`EngineeringContract` — structured, persisted components with file
  role, required symbols/signature, return type, units, formats, error behavior,
  forbidden extras, import contract, test cases, requirement ids, classification,
  ambiguity, version and hash;
* role detection by directory + filename + extension + requirement intent,
  with explicit ambiguity instead of silent guessing;
* :func:`validate_contract_plan` — rejects a plan before any provider dispatch
  when a mandatory requirement is unassigned, a role conflicts, a user-named
  file is missing, a target is duplicated or demand exceeds capacity;
* :func:`validate_cross_file` — static import/symbol/signature/return/extra-API
  checks across generated files (explicitly not a proof of semantic
  correctness);
* :func:`repair_test_imports` — deterministic import-path repair (no dispatch);
* :func:`test_inventory` / :func:`audit_test_repair` — stable test inventory and
  coverage-preserving repair audit.
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

log = logging.getLogger("crusor.orchestration.contract")


# --------------------------------------------------------------------------- #
# roles and classifications
# --------------------------------------------------------------------------- #

class FileRole(str, Enum):
    SOURCE = "SOURCE"
    TEST = "TEST"
    CONFIGURATION = "CONFIGURATION"
    DOCUMENTATION = "DOCUMENTATION"
    BUILD = "BUILD"
    UNKNOWN = "UNKNOWN"


class ContractClassification(str, Enum):
    EXPLICIT = "EXPLICIT"
    NECESSARY_INFERRED = "NECESSARY_INFERRED"
    OPTIONAL_SUGGESTION = "OPTIONAL_SUGGESTION"


_TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs", "testcases"}
_CONFIG_NAMES = {
    "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "package.json",
    "tsconfig.json", "conftest.py", ".flake8", "mypy.ini", "ruff.toml",
}
_BUILD_NAMES = {"makefile", "dockerfile", "build.sh", "requirements.txt", "package-lock.json"}
_DOC_EXTS = {".md", ".rst", ".txt", ".adoc"}
_SOURCE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".php",
    ".cs", ".c", ".cpp", ".h",
}
_ALLOWED_RETURNS = {
    "int", "integer", "str", "string", "bool", "boolean", "float", "list",
    "dict", "timedelta", "bytes", "none", "set", "tuple",
}
_RETURN_MAP = {
    "integer": "int", "string": "str", "boolean": "bool", "none": "None",
}


def normalize_path(path: str) -> str:
    cleaned = str(path or "").strip().strip("`'\"()[]<>.,;:").replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = re.sub(r"/{2,}", "/", cleaned)
    return cleaned


def detect_file_role(path: str, intent: Optional[FileRole] = None) -> FileRole:
    """Detect a file role from structure, conventions and requirement intent.

    Directory wins for test/spec folders; a file named ``test_*`` under a source
    directory is ambiguous and follows the requirement intent instead of
    silently becoming a test.
    """
    normalized = normalize_path(path)
    if not normalized:
        return FileRole.UNKNOWN
    pure = PurePosixPath(normalized)
    lowered_parts = [part.lower() for part in pure.parts]
    dirs = set(lowered_parts[:-1])
    name = pure.name.lower()
    stem = pure.stem.lower()
    ext = pure.suffix.lower()

    if dirs & _TEST_DIRS:
        return FileRole.TEST
    if ext in _DOC_EXTS:
        return FileRole.DOCUMENTATION
    if name in _CONFIG_NAMES or ext in {".ini", ".toml", ".yaml", ".yml", ".cfg"}:
        return FileRole.CONFIGURATION
    if name in _BUILD_NAMES or name.startswith("dockerfile"):
        return FileRole.BUILD
    if "build" in dirs and ext in {".py", ".sh", ".ps1", ".mk"}:
        return FileRole.BUILD
    if "config" in dirs and ext in {".json", ".yaml", ".yml", ".toml"}:
        return FileRole.CONFIGURATION
    looks_like_test = (
        name.startswith("test_") or stem.endswith("_test")
        or ".test." in name or ".spec." in name
    )
    if looks_like_test:
        if intent == FileRole.TEST:
            return FileRole.TEST
        if intent == FileRole.SOURCE:
            return FileRole.SOURCE
        return FileRole.TEST
    if ext in _SOURCE_EXTS:
        return FileRole.SOURCE
    return FileRole.UNKNOWN


def requirement_intent(description: str) -> FileRole:
    """Classify a requirement's FILE role from its wording.

    The verb "build" is product language ("build an app/store") and must not
    turn a normal feature requirement into a BUILD-file requirement; only
    build-system nouns do. Same for bare "setup" (a business setup is not
    setup.py). This was the root of the Phase 11.6 REQ-001 failures.
    """
    lowered = (description or "").lower()
    if re.search(r"\b(?:tests?|pytest|unittest|specs?|coverage|fixtures?|assertions?)\b", lowered):
        return FileRole.TEST
    if re.search(
        r"\b(?:pytest\.ini|pyproject|package\.json|tsconfig|config(?:uration)?|"
        r"setup\.py|setup\.cfg|dotenv|\.env)\b",
        lowered,
    ):
        return FileRole.CONFIGURATION
    if re.search(r"\b(?:readme|documentation|docs?|docstring)\b", lowered):
        return FileRole.DOCUMENTATION
    if re.search(
        r"\b(?:makefile|dockerfile|docker-compose|build system|build script|"
        r"build pipeline|ci build|requirements\.txt|setup\.py)\b",
        lowered,
    ):
        return FileRole.BUILD
    return FileRole.SOURCE


# --------------------------------------------------------------------------- #
# contract model
# --------------------------------------------------------------------------- #

@dataclass
class ContractComponent:
    component_id: str
    name: str
    responsibility: str
    target_file: str
    role: str
    requirement_ids: List[str] = field(default_factory=list)
    classification: str = ContractClassification.EXPLICIT.value
    symbols: List[str] = field(default_factory=list)
    signatures: Dict[str, List[str]] = field(default_factory=dict)
    returns: Optional[str] = None
    units: List[str] = field(default_factory=list)
    formats: List[str] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)
    forbidden: List[str] = field(default_factory=list)
    edge_cases: List[str] = field(default_factory=list)
    imports: List[Dict[str, Any]] = field(default_factory=list)
    test_cases: List[Dict[str, Any]] = field(default_factory=list)
    evidence_required: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_id": self.component_id,
            "name": self.name,
            "responsibility": self.responsibility,
            "target_file": self.target_file,
            "role": self.role,
            "requirement_ids": self.requirement_ids,
            "classification": self.classification,
            "symbols": self.symbols,
            "signatures": self.signatures,
            "returns": self.returns,
            "units": self.units,
            "formats": self.formats,
            "errors": self.errors,
            "forbidden": self.forbidden,
            "edge_cases": self.edge_cases,
            "imports": self.imports,
            "test_cases": self.test_cases,
            "evidence_required": self.evidence_required,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContractComponent":
        return cls(**{key: data.get(key) for key in cls.__dataclass_fields__})


@dataclass
class EngineeringContract:
    task_id: str
    prompt_sha256: str
    version: int = 1
    components: List[ContractComponent] = field(default_factory=list)
    requirement_map: Dict[str, List[str]] = field(default_factory=dict)
    ambiguities: List[str] = field(default_factory=list)
    optional_suggestions: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def contract_hash(self) -> str:
        payload = json.dumps(
            {
                "task_id": self.task_id,
                "prompt_sha256": self.prompt_sha256,
                "version": self.version,
                "components": [c.to_dict() for c in self.components],
                "requirement_map": self.requirement_map,
                "ambiguities": self.ambiguities,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_id": f"CONTRACT-{self.contract_hash[:12]}",
            "task_id": self.task_id,
            "prompt_sha256": self.prompt_sha256,
            "version": self.version,
            "components": [c.to_dict() for c in self.components],
            "requirement_map": self.requirement_map,
            "ambiguities": self.ambiguities,
            "optional_suggestions": self.optional_suggestions,
            "contract_hash": self.contract_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineeringContract":
        return cls(
            task_id=data.get("task_id", ""),
            prompt_sha256=data.get("prompt_sha256", ""),
            version=int(data.get("version", 1)),
            components=[ContractComponent.from_dict(c) for c in data.get("components", [])],
            requirement_map=data.get("requirement_map", {}),
            ambiguities=data.get("ambiguities", []),
            optional_suggestions=data.get("optional_suggestions", []),
        )

    def component_for(self, target_file: str) -> Optional[ContractComponent]:
        normalized = normalize_path(target_file)
        return next(
            (c for c in self.components if normalize_path(c.target_file) == normalized),
            None,
        )

    def persist(self, workspace: str | Path) -> str:
        root = Path(workspace) / ".crusorai" / "contracts"
        root.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.task_id)
        path = root / f"{safe}_contract.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return str(path)


# --------------------------------------------------------------------------- #
# prompt parsing
# --------------------------------------------------------------------------- #

def _split_params(params: str) -> List[str]:
    if not params.strip():
        return []
    cleaned = re.sub(r"(\w+)\s*:\s*[^,=]+", r"\1", params)
    cleaned = re.sub(r"=\s*[^,]+", "", cleaned)
    return [p.strip().lstrip("*") for p in cleaned.split(",") if p.strip()]


def parse_prompt_contract(prompt: str) -> Dict[str, Any]:
    """Extract explicit contract fields from the user's own words."""
    text = prompt or ""
    lowered = text.lower()

    symbols: List[str] = []
    signatures: Dict[str, List[str]] = {}
    # A callable named with parentheses is the unambiguous form.
    for match in re.finditer(r"\b(?:def|function)\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", text):
        name = match.group(1)
        if name not in symbols:
            symbols.append(name)
            signatures[name] = _split_params(match.group(2) or "")
    # "public function parse_duration" without a signature: refuse prose words.
    _symbol_stopwords = {
        "exactly", "as", "that", "which", "with", "in", "from", "must", "should",
        "then", "and", "or", "to", "is", "are", "be", "the", "a", "an", "only",
        "one", "public", "private", "returns", "calls", "takes", "has",
    }
    for match in re.finditer(r"\b(?:public\s+)?function\s+([A-Za-z_]\w*)\b", text):
        name = match.group(1)
        if name.lower() in _symbol_stopwords or name in symbols:
            continue
        symbols.append(name)
        signatures.setdefault(name, [])

    returns = None
    return_match = re.search(
        r"\breturns?\s+(?:an?\s+)?([A-Za-z_]+)\b", lowered,
    )
    if return_match and return_match.group(1) in _ALLOWED_RETURNS:
        returns = _RETURN_MAP.get(return_match.group(1), return_match.group(1))

    units: List[str] = []
    unit_match = re.search(r"supported units?\s*:\s*([^.\n]+)", text, re.IGNORECASE)
    if unit_match:
        raw = unit_match.group(1)
        units = [
            token for token in re.split(r"[,/]|\band\b", raw)
            if token.strip() and len(token.strip()) <= 16
        ]
        units = [u.strip().strip("`'\".") for u in units if u.strip()]

    errors: List[Dict[str, str]] = []
    for match in re.finditer(
        r"\bRaise\s+(ValueError|TypeError|KeyError|RuntimeError|IndexError|Exception)"
        r"(?:\s+(?:for|when|if)\s+([^.;]+))?",
        text,
    ):
        errors.append({"type": match.group(1), "when": (match.group(2) or "").strip()})

    forbidden: List[str] = []
    for match in re.finditer(r"\bDo not accept\s+([^.\n]+)", text, re.IGNORECASE):
        forbidden.append(match.group(1).strip().rstrip("."))
    if re.search(r"exactly one public function", lowered):
        forbidden.append("additional public functions, classes, constants or CLI")
    if re.search(r"\bno\s+(?:classes|cli|command[- ]line|examples)\b", lowered):
        forbidden.append("classes, CLI or examples")
    if re.search(r"do not modify unrelated files", lowered):
        forbidden.append("modifying unrelated files")

    imports: List[Dict[str, Any]] = []
    for match in re.finditer(
        r"from\s+([A-Za-z_][\w.]*)\s+import\s+([A-Za-z_][\w,\s]*)(?=[`'\".,;\n]|$)",
        text,
    ):
        names = [n.strip() for n in match.group(2).split(",") if n.strip()]
        imports.append({"module": match.group(1), "symbols": names, "style": "from"})
    # Bare imports are only recognized on their own line; prose like
    # "import the function exactly as ..." is not an import instruction.
    for match in re.finditer(r"(?m)^\s*import\s+([A-Za-z_][\w.]*)\s*$", text):
        module = match.group(1)
        if module.lower() in {"the", "a", "an", "this", "that"}:
            continue
        if not any(i["module"] == module for i in imports):
            imports.append({"module": module, "symbols": [], "style": "import"})

    test_cases: List[Dict[str, Any]] = []
    for match in re.finditer(
        r"['\"]([^'\"]+)['\"]\s*(?:->|→)\s*(['\"]?[A-Za-z0-9_.+-]+['\"]?)",
        text,
    ):
        raw = match.group(2).strip("'\"")
        expected: Any = raw
        try:
            expected = int(raw)
        except ValueError:
            if raw.lower() in {"true", "false"}:
                expected = raw.lower() == "true"
        test_cases.append({"input": match.group(1), "expected": expected})
    for match in re.finditer(
        r"['\"]([^'\"]+)['\"]\s+raises?\s+(ValueError|TypeError|KeyError|RuntimeError|IndexError)",
        text,
        re.IGNORECASE,
    ):
        test_cases.append({"input": match.group(1), "raises": match.group(2)})
    if re.search(r"non-string raises?\s+TypeError", lowered):
        test_cases.append({"input": "non-string", "raises": "TypeError"})

    edge_cases: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if re.search(
            r"\b(?:empty|invalid|boundary|duplicate|negative|unknown|missing|non-string|"
            r"whitespace|spaces?|order|optional|float|multiple)\b",
            sentence.lower(),
        ):
            stripped = sentence.strip()
            if stripped and stripped not in edge_cases:
                edge_cases.append(stripped)

    return {
        "symbols": symbols,
        "signatures": signatures,
        "returns": returns,
        "units": units,
        "errors": errors,
        "forbidden": forbidden,
        "imports": imports,
        "test_cases": test_cases,
        "edge_cases": edge_cases,
        "exactly_one_public": "exactly one public function" in lowered,
    }


# --------------------------------------------------------------------------- #
# extraction + assignment
# --------------------------------------------------------------------------- #

_FILE_MENTION_RE = re.compile(
    r"[A-Za-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|json|md|toml|yaml|yml|ini|cfg|txt)\b"
)


def _requirement_id(req: Any) -> str:
    return getattr(req, "id", "") or getattr(req, "req_id", "") or "REQ-UNKNOWN"


def _requirement_description(req: Any) -> str:
    return getattr(req, "description", "") or getattr(req, "title", "") or ""


def _requirement_classification(req: Any) -> str:
    raw = getattr(req, "classification", None)
    value = str(getattr(raw, "value", raw) or "").upper()
    if value in {"REASONABLE_DEFAULT", "DISCOVERABLE", "USER_DECISION_REQUIRED", "OPTIONAL_SUGGESTION"}:
        return ContractClassification.OPTIONAL_SUGGESTION.value
    if value in {"NECESSARY_INFERRED"}:
        return ContractClassification.NECESSARY_INFERRED.value
    return ContractClassification.EXPLICIT.value


def _mentioned_files(text: str) -> List[str]:
    found: List[str] = []
    for token in _FILE_MENTION_RE.findall(text or ""):
        path = normalize_path(token)
        if path and path not in found:
            found.append(path)
    return found


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return cleaned or "task"


def _synthesize_target(intent: FileRole, requirement_id: str) -> str:
    """Deterministic, role-appropriate path for a necessary inferred file."""
    slug = _slug(requirement_id)
    if intent == FileRole.CONFIGURATION:
        return f"config/{slug}.yaml"
    if intent == FileRole.DOCUMENTATION:
        return f"docs/{slug}.md"
    if intent == FileRole.BUILD:
        return f"build/{slug}.py"
    if intent == FileRole.TEST:
        return f"tests/test_{slug}.py"
    return f"src/{slug}_module.py"


def extract_contract(
    prompt: str,
    requirements: Iterable[Any],
    requested_files: Iterable[str],
    *,
    task_id: str,
    workspace: str | Path,
) -> EngineeringContract:
    """Build the authoritative contract for this task BEFORE planning."""
    prompt = prompt or ""
    requested = [normalize_path(f) for f in requested_files if normalize_path(f)]
    requested = list(dict.fromkeys(requested))
    fields = parse_prompt_contract(prompt)

    mandatory: List[Any] = []
    optional: List[Dict[str, Any]] = []
    for req in requirements:
        classification = _requirement_classification(req)
        if classification == ContractClassification.OPTIONAL_SUGGESTION.value:
            optional.append({
                "id": _requirement_id(req),
                "description": _requirement_description(req),
                "classification": classification,
            })
        else:
            mandatory.append(req)

    detected_roles: Dict[str, FileRole] = {}
    for path in requested:
        detected_roles[path] = detect_file_role(path)

    component_files: Dict[str, Set[str]] = {}
    file_requirements: Dict[str, List[str]] = {}
    file_responsibilities: Dict[str, List[str]] = {}
    roles: Dict[str, FileRole] = dict(detected_roles)
    ambiguities: List[str] = []
    if len(fields["symbols"]) > 1 and re.search(r"\bpublic\s+function\b", prompt, re.IGNORECASE):
        ambiguities.append(
            "conflicting required symbols: " + ", ".join(fields["symbols"])
        )
    if re.search(r"\b(?:public\s+)?function\b", prompt, re.IGNORECASE) and not fields["symbols"]:
        ambiguities.append("no public symbol is specified for the requested function")

    source_files = [f for f in requested if detected_roles[f] == FileRole.SOURCE]
    test_files = [f for f in requested if detected_roles[f] == FileRole.TEST]

    def _choose_test_file(intent_files: List[str], source_target: Optional[str]) -> Optional[str]:
        if not intent_files:
            return None
        if source_target:
            source_stem = PurePosixPath(source_target).stem.lower()
            for candidate in intent_files:
                if source_stem and source_stem in PurePosixPath(candidate).stem.lower():
                    return candidate
        return intent_files[0]

    assigned_sources: List[str] = []

    for req in mandatory:
        rid = _requirement_id(req)
        description = _requirement_description(req)
        if not str(description or "").strip():
            ambiguities.append(f"{rid} has no description and no target can be inferred")
            continue
        intent = requirement_intent(description)
        explicit = _mentioned_files(description)
        target: Optional[str] = None
        role = intent

        # One sentence may name both the source and its test. Map the
        # requirement to BOTH role-correct files instead of assigning one and
        # absorbing the other.
        explicit_detected = [
            (path, detect_file_role(path)) for path in explicit
        ]
        explicit_roles = {
            detected for _, detected in explicit_detected
            if detected in {FileRole.SOURCE, FileRole.TEST}
        }
        if len(explicit_roles) > 1:
            for path, detected in explicit_detected:
                if detected not in {FileRole.SOURCE, FileRole.TEST}:
                    continue
                normalized = normalize_path(path)
                roles[normalized] = detected
                file_requirements.setdefault(normalized, [])
                if rid not in file_requirements[normalized]:
                    file_requirements[normalized].append(rid)
                file_responsibilities.setdefault(normalized, [])
                if description and description not in file_responsibilities[normalized]:
                    file_responsibilities[normalized].append(description)
                if detected == FileRole.SOURCE and normalized not in assigned_sources:
                    assigned_sources.append(normalized)
            continue

        # 1. Explicit file mentioned in the requirement wins if the role agrees.
        for path in explicit:
            detected = detect_file_role(path, intent=intent)
            if intent == FileRole.SOURCE and detected == FileRole.SOURCE:
                target, role = path, FileRole.SOURCE
                break
            if intent == FileRole.TEST and (detected == FileRole.TEST or not path.lower().startswith(("src/", "lib/", "app/"))):
                target, role = path, FileRole.TEST
                break
            if detected == intent:
                target, role = path, detected
                break

        # 2. Otherwise choose from the requested pool by role.
        if target is None and intent == FileRole.TEST:
            target = _choose_test_file(test_files, assigned_sources[-1] if assigned_sources else None)
            role = FileRole.TEST
        elif target is None and intent == FileRole.SOURCE:
            target = source_files[0] if source_files else None
            role = FileRole.SOURCE
        elif target is None:
            pool = [f for f in requested if roles.get(f) == intent]
            target = pool[0] if pool else None

        # 3. Synthesize a necessary path only when the user named none of that role.
        if target is None and intent == FileRole.TEST:
            source_stem = PurePosixPath(assigned_sources[0]).stem if assigned_sources else _slug(rid)
            target = f"tests/test_{source_stem}.py"
            role = FileRole.TEST
        elif target is None and intent == FileRole.SOURCE:
            target = f"src/{_slug(rid)}_module.py"
            role = FileRole.SOURCE
        elif target is None:
            # Config/doc/build with no explicit or requested file: a necessary
            # role-appropriate artifact is safer than attaching the requirement
            # to an unrelated source file (which produced a role conflict and
            # rejected the whole plan). The path is deterministic per
            # requirement id, so contract hashes stay stable and traceability is
            # preserved. No arbitrary file is invented for SOURCE/TEST.
            target = _synthesize_target(intent, rid)
            role = intent

        if target is None:
            ambiguities.append(f"{rid} could not be assigned any target file")
            continue

        normalized = normalize_path(target)
        detected = detect_file_role(normalized, intent=intent)
        if role == FileRole.SOURCE and detected == FileRole.TEST:
            ambiguities.append(
                f"source requirement {rid} resolved to test file {normalized}"
            )
        if role == FileRole.TEST and detected == FileRole.SOURCE and "/" in normalized:
            if "test" not in normalized.lower() and "spec" not in normalized.lower():
                ambiguities.append(
                    f"test requirement {rid} resolved to source file {normalized}"
                )
        roles[normalized] = role
        if role == FileRole.SOURCE and normalized not in assigned_sources:
            assigned_sources.append(normalized)
        file_requirements.setdefault(normalized, [])
        if rid not in file_requirements[normalized]:
            file_requirements[normalized].append(rid)
        file_responsibilities.setdefault(normalized, [])
        if description and description not in file_responsibilities[normalized]:
            file_responsibilities[normalized].append(description)

    # Every user-named file is a work unit even when no requirement mentions it.
    for path in requested:
        if path not in file_requirements:
            file_requirements[path] = []
            file_responsibilities[path] = []
            if path not in roles:
                roles[path] = detect_file_role(path)

    components: List[ContractComponent] = []
    for path in list(dict.fromkeys([*requested, *file_requirements.keys()])):
        role = roles.get(path) or detect_file_role(path)
        if role == FileRole.UNKNOWN:
            ambiguities.append(f"file role for {path} is unknown")
        req_ids = file_requirements.get(path, [])
        responsibilities = file_responsibilities.get(path, [])
        component = ContractComponent(
            component_id=f"COMP-{len(components) + 1:03d}",
            name=PurePosixPath(path).stem,
            responsibility=" | ".join(responsibilities)[:600],
            target_file=path,
            role=role.value,
            requirement_ids=req_ids,
            classification=(
                ContractClassification.EXPLICIT.value if req_ids
                else ContractClassification.NECESSARY_INFERRED.value
            ),
            symbols=list(fields["symbols"]) if role == FileRole.SOURCE else [],
            signatures=dict(fields["signatures"]) if role == FileRole.SOURCE else {},
            returns=fields["returns"] if role == FileRole.SOURCE else None,
            units=list(fields["units"]) if role == FileRole.SOURCE else [],
            formats=list(fields["edge_cases"])[:6] if role == FileRole.SOURCE else [],
            errors=list(fields["errors"]),
            forbidden=list(fields["forbidden"]),
            edge_cases=list(fields["edge_cases"]),
            imports=(
                list(fields["imports"]) if role == FileRole.TEST
                else []
            ),
            test_cases=list(fields["test_cases"]) if role == FileRole.TEST else [],
            evidence_required=(
                ["pytest executed", "public symbol present", "return contract satisfied"]
                if role == FileRole.SOURCE
                else ["tests executed", "import contract satisfied"]
            ),
        )
        components.append(component)

    requirement_map: Dict[str, List[str]] = {}
    for path, req_ids in file_requirements.items():
        for rid in req_ids:
            requirement_map.setdefault(rid, [])
            if path not in requirement_map[rid]:
                requirement_map[rid].append(path)

    # The test generator must see the same public API as the source generator.
    source_components = [c for c in components if c.role == FileRole.SOURCE.value]
    if source_components:
        api_owner = source_components[0]
        for component in components:
            if component.role != FileRole.TEST.value:
                continue
            component.symbols = list(api_owner.symbols)
            component.signatures = dict(api_owner.signatures)
            component.returns = api_owner.returns
            component.units = list(api_owner.units)
            component.errors = list(api_owner.errors)
            component.forbidden = list(api_owner.forbidden)

    contract = EngineeringContract(
        task_id=task_id,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        components=components,
        requirement_map=requirement_map,
        ambiguities=ambiguities,
        optional_suggestions=optional,
    )
    contract.persist(workspace)
    return contract


# --------------------------------------------------------------------------- #
# plan validation
# --------------------------------------------------------------------------- #

class PlanValidationError(RuntimeError):
    """The contract cannot be turned into a safe provider plan."""

    def __init__(self, reasons: List[str], *, work_units: int = 0, demand: int = 0):
        self.reasons = reasons
        self.work_units = work_units
        self.demand = demand
        super().__init__("plan rejected before dispatch: " + "; ".join(reasons))


def plan_work_units(plan: Any) -> List[Any]:
    return [
        node for node in plan.nodes.values()
        if node.node_id != "task_verification" and node.target_files
    ]


def validate_contract_plan(
    contract: EngineeringContract,
    plan: Any,
    *,
    max_dispatches: Optional[int],
    requested_files: Iterable[str] = (),
) -> Dict[str, Any]:
    """Validate Requirement → Role → File → Work Unit BEFORE any dispatch."""
    reasons: List[str] = []
    units = plan_work_units(plan)
    demand = sum(max(1, len(node.target_files)) for node in units)

    if not units:
        reasons.append("plan has no implementation work units")

    # Every mandatory requirement has an explicit, role-correct assignment.
    for req_id, files in contract.requirement_map.items():
        if not files:
            reasons.append(f"mandatory requirement {req_id} has no target file")
            continue
        nodes = [n for n in units if req_id in n.related_requirement_ids]
        if not nodes:
            reasons.append(f"mandatory requirement {req_id} is missing from the plan")
            continue
        for target in files:
            if not any(normalize_path(target) in {normalize_path(f) for f in n.target_files} for n in nodes):
                reasons.append(
                    f"requirement {req_id} is planned but target {target} is absent"
                )

    # No source/test role conflicts; no duplicate work units.
    seen: Dict[str, str] = {}
    for node in units:
        node_role = getattr(node, "file_role", "") or ""
        for target in node.target_files:
            normalized = normalize_path(target)
            component = contract.component_for(normalized)
            role = component.role if component else detect_file_role(normalized)
            if node_role and role and node_role != role and role != FileRole.UNKNOWN.value:
                reasons.append(
                    f"node {node.node_id} role {node_role} conflicts with {normalized} ({role})"
                )
            if normalized in seen and seen[normalized] != node.node_id:
                reasons.append(
                    f"duplicate work unit for {normalized}: "
                    f"{seen[normalized]} and {node.node_id}"
                )
            seen[normalized] = node.node_id

    # Every user-named file has exactly one work unit.
    for path in requested_files:
        normalized = normalize_path(path)
        count = sum(1 for n in units if normalized in {normalize_path(f) for f in n.target_files})
        if count == 0:
            reasons.append(f"user-named file {normalized} has no work unit")
        elif count > 1:
            reasons.append(f"user-named file {normalized} has {count} work units")

    # No mandatory requirement disappears during coalescing.
    planned_ids = {rid for n in units for rid in n.related_requirement_ids}
    for req_id in contract.requirement_map:
        if req_id not in planned_ids:
            reasons.append(f"requirement {req_id} was lost during coalescing")

    if max_dispatches is not None and demand > int(max_dispatches):
        reasons.append(
            f"dispatch demand {demand} exceeds available capacity {int(max_dispatches)}"
        )

    if contract.ambiguities:
        # Ambiguity that affects mandatory work is a pre-dispatch failure.
        reasons.extend(f"contract ambiguity: {a}" for a in contract.ambiguities)

    report = {
        "ok": not reasons,
        "reasons": reasons,
        "work_units": len(units),
        "demand": demand,
        "targets": sorted(seen),
        "contract_hash": contract.contract_hash,
        "requirements": contract.requirement_map,
    }
    if reasons:
        raise PlanValidationError(reasons, work_units=len(units), demand=demand)
    return report


# --------------------------------------------------------------------------- #
# cross-file validation
# --------------------------------------------------------------------------- #

def _parse(path: Path) -> Optional[ast.AST]:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (OSError, SyntaxError):
        return None


def _public_symbols(tree: ast.AST) -> Dict[str, ast.AST]:
    symbols: Dict[str, ast.AST] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                symbols[node.name] = node
    return symbols


def _defined_names(tree: ast.AST) -> Set[str]:
    """Every importable module-level name (functions, classes, assignments)."""
    names: Set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _function_params(node: ast.AST) -> List[str]:
    args = getattr(node, "args", None)
    if not args:
        return []
    names = [a.arg for a in getattr(args, "posonlyargs", [])]
    names += [a.arg for a in getattr(args, "args", [])]
    return names


def _annotation_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant):
        return str(node.value)
    return None


def _module_path_for_file(path: str) -> str:
    normalized = normalize_path(path)
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    return normalized.replace("/", ".")


def validate_cross_file(
    workspace: str | Path,
    contract: EngineeringContract,
    mutated_files: Iterable[str],
) -> Dict[str, Any]:
    """Static cross-file consistency: imports, symbols, signature, return, extras.

    A clean report is NOT proof of semantic correctness; execution remains the
    authority. Findings are persisted and fed into diagnosis/completion.
    """
    root = Path(workspace).resolve()
    mutated = [normalize_path(f) for f in mutated_files]
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    checked: Dict[str, Any] = {}

    source_components = [c for c in contract.components if c.role == FileRole.SOURCE.value]
    source_trees: Dict[str, ast.AST] = {}
    for component in source_components:
        path = root / component.target_file
        if not path.exists():
            errors.append({
                "code": "missing_source",
                "file": component.target_file,
                "message": "source artifact was not generated",
                "requirement_ids": component.requirement_ids,
            })
            continue
        tree = _parse(path)
        if tree is None:
            errors.append({
                "code": "source_unparseable",
                "file": component.target_file,
                "message": "source artifact is not valid Python",
                "requirement_ids": component.requirement_ids,
            })
            continue
        source_trees[component.target_file] = tree
        public = _public_symbols(tree)
        checked[component.target_file] = {
            "role": "SOURCE",
            "public_symbols": sorted(public),
        }

        for symbol in component.symbols:
            if symbol not in public:
                errors.append({
                    "code": "missing_symbol",
                    "file": component.target_file,
                    "message": f"required public symbol '{symbol}' is missing",
                    "requirement_ids": component.requirement_ids,
                })
                continue
            expected_params = component.signatures.get(symbol) or []
            actual_params = _function_params(public[symbol])
            if expected_params and actual_params[:len(expected_params)] != expected_params:
                errors.append({
                    "code": "signature_mismatch",
                    "file": component.target_file,
                    "message": (
                        f"'{symbol}' parameters {actual_params} do not match "
                        f"contract {expected_params}"
                    ),
                    "requirement_ids": component.requirement_ids,
                })
            if component.returns:
                annotation = _annotation_name(getattr(public[symbol], "returns", None)) \
                    if getattr(public[symbol], "returns", None) is not None else None
                if annotation and annotation != component.returns:
                    errors.append({
                        "code": "return_type_mismatch",
                        "file": component.target_file,
                        "message": (
                            f"'{symbol}' returns {annotation}; contract requires "
                            f"{component.returns}"
                        ),
                        "requirement_ids": component.requirement_ids,
                    })
                if component.returns in {"int", "str", "bool", "float"}:
                    content = (root / component.target_file).read_text(
                        encoding="utf-8", errors="replace"
                    )
                    if "timedelta" in content and component.returns == "int":
                        errors.append({
                            "code": "return_contract_violation",
                            "file": component.target_file,
                            "message": "implementation uses timedelta but the contract requires int seconds",
                            "requirement_ids": component.requirement_ids,
                        })

        if any("exactly one public function" in f.lower() for f in component.forbidden):
            if len(public) > 1:
                errors.append({
                    "code": "extra_public_api",
                    "file": component.target_file,
                    "message": "contract allows exactly one public function; found "
                               + ", ".join(sorted(public)),
                    "requirement_ids": component.requirement_ids,
                })
        lowered_forbidden = " ".join(component.forbidden).lower()
        content = (root / component.target_file).read_text(encoding="utf-8", errors="replace")
        if "float" in lowered_forbidden and re.search(r"\bfloat\s*\(", content):
            errors.append({
                "code": "forbidden_float",
                "file": component.target_file,
                "message": "contract says floats are not accepted; implementation calls float()",
                "requirement_ids": component.requirement_ids,
            })
        if re.search(r"\b(?:cli|command[- ]line)\b", lowered_forbidden) and re.search(
            r"\b(?:argparse|click|sys\.argv)\b", content
        ):
            errors.append({
                "code": "forbidden_cli",
                "file": component.target_file,
                "message": "contract forbids a CLI; implementation references one",
                "requirement_ids": component.requirement_ids,
            })

    # Test imports must resolve to generated source and expose the symbols.
    source_by_module = {
        _module_path_for_file(c.target_file): c for c in source_components
    }
    source_by_stem = {
        PurePosixPath(c.target_file).stem: c for c in source_components
    }
    for component in [c for c in contract.components if c.role == FileRole.TEST.value]:
        path = root / component.target_file
        if not path.exists():
            errors.append({
                "code": "missing_test",
                "file": component.target_file,
                "message": "test artifact was not generated",
                "requirement_ids": component.requirement_ids,
            })
            continue
        tree = _parse(path)
        if tree is None:
            errors.append({
                "code": "test_unparseable",
                "file": component.target_file,
                "message": "test artifact is not valid Python",
                "requirement_ids": component.requirement_ids,
            })
            continue
        imports_found: List[Dict[str, Any]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports_found.append({
                    "module": node.module,
                    "symbols": [alias.name for alias in node.names],
                })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports_found.append({
                        "module": alias.name,
                        "symbols": [],
                        "alias": alias.asname,
                    })
        checked[component.target_file] = {"role": "TEST", "imports": imports_found}

        for item in imports_found:
            module = item["module"]
            if module in source_by_module:
                source_component = source_by_module[module]
            elif module in source_by_stem:
                source_component = source_by_stem[module]
                errors.append({
                    "code": "wrong_import_path",
                    "file": component.target_file,
                    "message": (
                        f"test imports '{module}' but the module is "
                        f"'{_module_path_for_file(source_component.target_file)}'"
                    ),
                    "requirement_ids": component.requirement_ids,
                })
            elif module.split(".")[0] in {"src", "app", "lib"}:
                errors.append({
                    "code": "missing_import_module",
                    "file": component.target_file,
                    "message": f"test imports '{module}' which does not resolve to a generated file",
                    "requirement_ids": component.requirement_ids,
                })
                continue
            else:
                continue
            tree_source = source_trees.get(source_component.target_file)
            if tree_source is None:
                continue
            defined = _defined_names(tree_source)
            for symbol in item["symbols"]:
                if symbol and symbol not in defined:
                    errors.append({
                        "code": "missing_imported_symbol",
                        "file": component.target_file,
                        "message": f"test imports '{symbol}' but it is not defined in {source_component.target_file}",
                        "requirement_ids": component.requirement_ids,
                    })

        for required in component.imports:
            module = required.get("module", "")
            if module and not any(i["module"] == module for i in imports_found):
                warnings.append({
                    "code": "contract_import_missing",
                    "file": component.target_file,
                    "message": f"test does not import the contract module '{module}'",
                    "requirement_ids": component.requirement_ids,
                })

    report = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_files": checked,
        "contract_hash": contract.contract_hash,
        "method": "static_ast",
        "note": "a clean static report is not proof of semantic correctness; execution is authoritative",
    }
    root_contracts = root / ".crusorai" / "contracts"
    root_contracts.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", contract.task_id)
    (root_contracts / f"{safe}_cross_file.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8",
    )
    return report


# --------------------------------------------------------------------------- #
# safe test repair helpers
# --------------------------------------------------------------------------- #

def build_test_inventory(content: str) -> Dict[str, Any]:
    """Stable inventory of test functions and verification strength."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return {"parseable": False, "functions": {}, "test_functions": {}}
    test_functions: Dict[str, Dict[str, Any]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test"):
                continue
            asserts = sum(
                1 for child in ast.walk(node) if isinstance(child, ast.Assert)
            )
            raises = sum(
                1 for child in ast.walk(node)
                if isinstance(child, ast.withitem)
                or (isinstance(child, ast.Attribute) and child.attr == "raises")
            )
            decorators = []
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute):
                    decorators.append(target.attr)
                elif isinstance(target, ast.Name):
                    decorators.append(target.id)
            test_functions[node.name] = {
                "asserts": asserts,
                "raises": raises,
                "decorators": sorted(decorators),
                "params": _function_params(node),
            }
    return {
        "parseable": True,
        "functions": {
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        },
        "test_functions": test_functions,
    }


def audit_test_repair(before: str, after: str) -> List[str]:
    """Reject repairs that remove tests or reduce verification strength."""
    old = build_test_inventory(before)
    new = build_test_inventory(after)
    violations: List[str] = []
    if not new.get("parseable"):
        return ["repaired test file is not syntactically valid"]
    if not old.get("parseable"):
        return violations  # nothing meaningful to preserve
    for name, stats in old["test_functions"].items():
        if name not in new["test_functions"]:
            violations.append(f"test function '{name}' was removed")
            continue
        current = new["test_functions"][name]
        if current["asserts"] < stats["asserts"]:
            violations.append(
                f"assertions reduced in '{name}': {stats['asserts']} -> {current['asserts']}"
            )
        if current["raises"] < stats["raises"]:
            violations.append(f"exception assertions reduced in '{name}'")
        if any(d in {"skip", "skipif", "xfail"} for d in current["decorators"]):
            if not any(d in {"skip", "skipif", "xfail"} for d in stats["decorators"]):
                violations.append(f"test '{name}' was converted to skip/xfail")
        if stats["params"] != current["params"]:
            violations.append(f"parameters changed in '{name}'")
    for name in new["test_functions"]:
        if name not in old["test_functions"] and not name.startswith("test"):
            violations.append(f"non-test function '{name}' added")
    return violations


def repair_test_imports(
    workspace: str | Path,
    target_file: str,
    contract: EngineeringContract,
) -> Tuple[bool, str, List[str]]:
    """Deterministically fix bare project imports in a generated test file.

    Example: ``from duration import parse_duration`` becomes
    ``from src.duration import parse_duration`` when the contract's source file
    is ``src/duration.py``. No provider dispatch and no assertion changes.
    """
    root = Path(workspace).resolve()
    path = root / target_file
    if not path.exists():
        return False, "", ["test file does not exist"]
    original = path.read_text(encoding="utf-8", errors="replace")
    updated = original
    notes: List[str] = []
    for component in contract.components:
        if component.role != FileRole.SOURCE.value:
            continue
        module = _module_path_for_file(component.target_file)
        stem = PurePosixPath(component.target_file).stem
        from_pattern = re.compile(rf"(?m)^(\s*)from\s+{re.escape(stem)}\s+import\b")
        if from_pattern.search(updated) and f"from {module} import" not in updated:
            updated = from_pattern.sub(rf"\1from {module} import", updated)
            notes.append(f"rewrote 'from {stem} import' -> 'from {module} import'")
        import_pattern = re.compile(rf"(?m)^(\s*)import\s+{re.escape(stem)}\s*$")
        if import_pattern.search(updated) and f"import {module}" not in updated:
            updated = import_pattern.sub(
                rf"\1import {module} as {stem}", updated,
            )
            notes.append(f"rewrote 'import {stem}' -> 'import {module} as {stem}'")

        # An invented symbol in a from-import (P0.6.7's `exactly`) is a contract
        # violation, not coverage. Drop it only when it is not used elsewhere;
        # a used-but-undefined symbol needs a test repair and is left alone.
        source_path = root / component.target_file
        if source_path.exists():
            source_tree = _parse(source_path)
            defined = _defined_names(source_tree) if source_tree is not None else set()
            # The contract's allowed symbols are authoritative. The current
            # source may itself contain the invented symbol that must go.
            allowed = {s for s in (component.symbols or [])} or defined
            from_re = re.compile(
                rf"(?m)^(\s*)from\s+{re.escape(module)}\s+import\s+([^\n]+)$"
            )
            for match in list(from_re.finditer(updated)):
                indent, names_blob = match.group(1), match.group(2)
                names = [n.strip() for n in names_blob.replace("(", "").replace(")", "").split(",") if n.strip()]
                kept: List[str] = []
                removed: List[str] = []
                for name in names:
                    bare = name.split(" as ")[0].strip()
                    if bare in allowed:
                        kept.append(name)
                        continue
                    # Is the missing name referenced outside this import line?
                    body = updated.replace(match.group(0), "", 1)
                    if re.search(rf"\b{re.escape(bare)}\b", body):
                        kept.append(name)
                    else:
                        removed.append(bare)
                if removed:
                    replacement = f"{indent}from {module} import " + ", ".join(kept) if kept else ""
                    updated = updated.replace(match.group(0), replacement, 1)
                    notes.append(
                        "removed invented import symbol(s) not in the contract: "
                        + ", ".join(removed)
                    )
    if updated == original:
        return False, original, notes
    try:
        ast.parse(updated)
    except SyntaxError as exc:
        return False, original, [f"rewritten import is invalid: {exc}"]
    violations = audit_test_repair(original, updated)
    if violations:
        return False, original, violations
    return True, updated, notes

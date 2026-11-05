"""
models.py -- Project & Repository Intelligence Data Models.

Phase 11.0: Project & Repository Intelligence.
Defines structured knowledge representations, evidence classifications,
confidence levels (VERIFIED, INFERRED, UNKNOWN), architecture maps,
and technology stack entities.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class ConfidenceLevel(str, enum.Enum):
    """
    Strict epistemic certainty classification:
    - VERIFIED: Directly established from repository files, manifests, or code structures.
    - INFERRED: Strongly suggested by naming, import patterns, or conventions.
    - UNKNOWN: Insufficient evidence to determine.
    """
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


@dataclass
class EvidenceFinding(Generic[T]):
    """An analytical finding paired with its epistemic confidence and source provenance."""
    value: T
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        val = self.value.value if isinstance(self.value, enum.Enum) else self.value
        return {
            "value": val,
            "confidence": self.confidence.value,
            "source_file": self.source_file,
            "line_number": self.line_number,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], val_parser: Any = None) -> EvidenceFinding[Any]:
        v = data.get("value")
        if val_parser and v is not None:
            v = val_parser(v)
        return cls(
            value=v,
            confidence=ConfidenceLevel(data.get("confidence", "UNKNOWN")),
            source_file=data.get("source_file"),
            line_number=data.get("line_number"),
            rationale=data.get("rationale", ""),
        )


class ProjectType(str, enum.Enum):
    WEB_APPLICATION = "WEB_APPLICATION"
    DESKTOP_ELECTRON = "DESKTOP_ELECTRON"
    API_SERVICE = "API_SERVICE"
    CLI_TOOL = "CLI_TOOL"
    LIBRARY = "LIBRARY"
    MONOREPO = "MONOREPO"
    MULTI_LANGUAGE = "MULTI_LANGUAGE"
    AI_AGENT_PLATFORM = "AI_AGENT_PLATFORM"
    UNKNOWN = "UNKNOWN"


@dataclass
class LanguageInfo:
    name: str
    file_count: int
    byte_count: int
    percentage: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "file_count": self.file_count,
            "byte_count": self.byte_count,
            "percentage": round(self.percentage, 2),
        }


@dataclass
class FrameworkInfo:
    name: str
    category: str  # backend, frontend, desktop, testing, build, agent
    evidence: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "evidence": self.evidence,
        }


@dataclass
class BuildCommands:
    build: Optional[str] = None
    run: Optional[str] = None
    test: Optional[str] = None
    lint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "build": self.build,
            "run": self.run,
            "test": self.test,
            "lint": self.lint,
        }


@dataclass
class EntryPoint:
    path: str
    entry_type: str  # main, server, cli, desktop_main, desktop_renderer, library
    evidence: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "entry_type": self.entry_type,
            "evidence": self.evidence,
        }


@dataclass
class ApiEndpoint:
    method: str
    path: str
    handler: str
    source_file: str
    framework: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "handler": self.handler,
            "source_file": self.source_file,
            "framework": self.framework,
        }


@dataclass
class DatabaseSchemaInfo:
    orm_or_driver: str
    migration_dir: Optional[str] = None
    model_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orm_or_driver": self.orm_or_driver,
            "migration_dir": self.migration_dir,
            "model_files": self.model_files,
        }


@dataclass
class ComponentNode:
    name: str
    category: str  # e.g. frontend, backend, agent_core, identity, finops, tools, runtime
    path: str
    responsibilities: List[str] = field(default_factory=list)
    internal_deps: List[str] = field(default_factory=list)
    external_deps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "path": self.path,
            "responsibilities": self.responsibilities,
            "internal_deps": self.internal_deps,
            "external_deps": self.external_deps,
        }


@dataclass
class ArchitectureMap:
    components: Dict[str, ComponentNode] = field(default_factory=dict)
    execution_flows: List[Dict[str, Any]] = field(default_factory=list)
    shared_utilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "components": {k: v.to_dict() for k, v in self.components.items()},
            "execution_flows": self.execution_flows,
            "shared_utilities": self.shared_utilities,
        }


@dataclass
class ProjectKnowledge:
    """Complete, persistent repository and project knowledge model."""
    project_name: str
    workspace_root: str
    project_purpose: EvidenceFinding[str]
    project_type: EvidenceFinding[ProjectType]
    languages: Dict[str, LanguageInfo] = field(default_factory=dict)
    frameworks: List[FrameworkInfo] = field(default_factory=list)
    build_commands: BuildCommands = field(default_factory=BuildCommands)
    entry_points: List[EntryPoint] = field(default_factory=list)
    source_dirs: List[str] = field(default_factory=list)
    test_dirs: List[str] = field(default_factory=list)
    config_files: List[str] = field(default_factory=list)
    api_endpoints: List[ApiEndpoint] = field(default_factory=list)
    database_info: Optional[DatabaseSchemaInfo] = None
    agent_tool_integrations: List[str] = field(default_factory=list)
    env_var_names: List[str] = field(default_factory=list)  # Only names, never secret values!
    architecture_map: ArchitectureMap = field(default_factory=ArchitectureMap)
    known_risks_and_limitations: List[str] = field(default_factory=list)
    git_info: Dict[str, Any] = field(default_factory=dict)
    last_scanned_timestamp: float = field(default_factory=time.time)
    scan_revision: str = ""
    discovery_confidence: float = 1.0
    file_mtimes: Dict[str, float] = field(default_factory=dict)  # rel_path -> mtime for incremental refresh

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "workspace_root": self.workspace_root,
            "project_purpose": self.project_purpose.to_dict(),
            "project_type": self.project_type.to_dict(),
            "languages": {k: v.to_dict() for k, v in self.languages.items()},
            "frameworks": [f.to_dict() for f in self.frameworks],
            "build_commands": self.build_commands.to_dict(),
            "entry_points": [e.to_dict() for e in self.entry_points],
            "source_dirs": self.source_dirs,
            "test_dirs": self.test_dirs,
            "config_files": self.config_files,
            "api_endpoints": [a.to_dict() for a in self.api_endpoints],
            "database_info": self.database_info.to_dict() if self.database_info else None,
            "agent_tool_integrations": self.agent_tool_integrations,
            "env_var_names": sorted(list(set(self.env_var_names))),
            "architecture_map": self.architecture_map.to_dict(),
            "known_risks_and_limitations": self.known_risks_and_limitations,
            "git_info": self.git_info,
            "last_scanned_timestamp": self.last_scanned_timestamp,
            "scan_revision": self.scan_revision,
            "discovery_confidence": round(self.discovery_confidence, 2),
            "file_mtimes": self.file_mtimes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectKnowledge:
        def parse_pt(val: str) -> ProjectType:
            try:
                return ProjectType(val)
            except ValueError:
                return ProjectType.UNKNOWN

        purpose = EvidenceFinding.from_dict(data.get("project_purpose", {"value": "Unknown"}))
        ptype = EvidenceFinding.from_dict(data.get("project_type", {"value": "UNKNOWN"}), val_parser=parse_pt)

        langs = {}
        for k, v in data.get("languages", {}).items():
            langs[k] = LanguageInfo(
                name=v.get("name", k),
                file_count=v.get("file_count", 0),
                byte_count=v.get("byte_count", 0),
                percentage=v.get("percentage", 0.0),
            )

        frameworks = [
            FrameworkInfo(name=f.get("name", ""), category=f.get("category", ""), evidence=f.get("evidence", ""))
            for f in data.get("frameworks", [])
        ]

        bc_data = data.get("build_commands", {})
        build_commands = BuildCommands(
            build=bc_data.get("build"),
            run=bc_data.get("run"),
            test=bc_data.get("test"),
            lint=bc_data.get("lint"),
        )

        entry_points = [
            EntryPoint(path=e.get("path", ""), entry_type=e.get("entry_type", ""), evidence=e.get("evidence", ""))
            for e in data.get("entry_points", [])
        ]

        api_endpoints = [
            ApiEndpoint(
                method=a.get("method", ""),
                path=a.get("path", ""),
                handler=a.get("handler", ""),
                source_file=a.get("source_file", ""),
                framework=a.get("framework", ""),
            )
            for a in data.get("api_endpoints", [])
        ]

        db_data = data.get("database_info")
        db_info = None
        if db_data:
            db_info = DatabaseSchemaInfo(
                orm_or_driver=db_data.get("orm_or_driver", ""),
                migration_dir=db_data.get("migration_dir"),
                model_files=db_data.get("model_files", []),
            )

        arch_data = data.get("architecture_map", {})
        components = {}
        for ck, cv in arch_data.get("components", {}).items():
            components[ck] = ComponentNode(
                name=cv.get("name", ck),
                category=cv.get("category", ""),
                path=cv.get("path", ""),
                responsibilities=cv.get("responsibilities", []),
                internal_deps=cv.get("internal_deps", []),
                external_deps=cv.get("external_deps", []),
            )

        arch_map = ArchitectureMap(
            components=components,
            execution_flows=arch_data.get("execution_flows", []),
            shared_utilities=arch_data.get("shared_utilities", []),
        )

        return cls(
            project_name=data.get("project_name", "Unknown"),
            workspace_root=data.get("workspace_root", ""),
            project_purpose=purpose,
            project_type=ptype,
            languages=langs,
            frameworks=frameworks,
            build_commands=build_commands,
            entry_points=entry_points,
            source_dirs=data.get("source_dirs", []),
            test_dirs=data.get("test_dirs", []),
            config_files=data.get("config_files", []),
            api_endpoints=api_endpoints,
            database_info=db_info,
            agent_tool_integrations=data.get("agent_tool_integrations", []),
            env_var_names=data.get("env_var_names", []),
            architecture_map=arch_map,
            known_risks_and_limitations=data.get("known_risks_and_limitations", []),
            git_info=data.get("git_info", {}),
            last_scanned_timestamp=data.get("last_scanned_timestamp", time.time()),
            scan_revision=data.get("scan_revision", ""),
            discovery_confidence=data.get("discovery_confidence", 1.0),
            file_mtimes=data.get("file_mtimes", {}),
        )


"""
src/impact/models.py - Change Impact Analysis Data Models.

Phase 11.4: Change Impact Analysis.
Defines strictly typed models for:
- Dependency graph levels, relationship types, and evidence sources.
- Graph nodes and edges with epistemic confidence and provenance.
- Impacted components, blast radius, and risk classifications.
- Public contract compatibility classifications.
- Comprehensive ChangeImpactReport schema.
"""

from __future__ import annotations

import enum
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


class GraphLevel(str, enum.Enum):
    """Abstraction levels represented in the multi-level dependency graph."""
    REPOSITORY = "REPOSITORY"      # Packages, applications, services, major subsystems
    MODULE = "MODULE"              # Files, libraries, internal packages, external dependencies
    SYMBOL = "SYMBOL"              # Functions, classes, methods, interfaces, types, constants
    APPLICATION = "APPLICATION"    # API endpoints, DB entities, config variables, jobs, events
    TEST = "TEST"                  # Unit, integration, e2e tests, fixtures, mocks


class RelationshipType(str, enum.Enum):
    """Semantic relationship types connecting dependency graph nodes."""
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    INSTANTIATES = "INSTANTIATES"
    READS = "READS"
    WRITES = "WRITES"
    EXPOSES = "EXPOSES"
    DEPENDS_ON = "DEPENDS_ON"
    CONFIGURES = "CONFIGURES"
    TESTS = "TESTS"
    MIGRATES = "MIGRATES"
    SERIALIZES = "SERIALIZES"
    DESERIALIZES = "DESERIALIZES"


class EvidenceSource(str, enum.Enum):
    """Evidence provenance source for nodes and relationship edges."""
    STATIC = "STATIC"                      # Discovered via static AST/syntax parsing
    RUNTIME_OBSERVED = "RUNTIME_OBSERVED"  # Discovered from coverage, logs, or traces
    HEURISTIC = "HEURISTIC"                # Inferred from conventions or naming patterns
    UNKNOWN = "UNKNOWN"                    # Unverified or ambiguous relationship


class ConfidenceLevel(str, enum.Enum):
    """Epistemic certainty of dependency finding."""
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class ImpactRisk(str, enum.Enum):
    """Evidence-based risk tier of proposed change or affected component."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class ContractCompatibility(str, enum.Enum):
    """Compatibility classification for public API or contract changes."""
    BACKWARD_COMPATIBLE = "BACKWARD_COMPATIBLE"
    POTENTIALLY_BREAKING = "POTENTIALLY_BREAKING"
    BREAKING = "BREAKING"
    UNKNOWN = "UNKNOWN"


class ChangeScopeCategory(str, enum.Enum):
    """Scope control categorization for proposed code changes."""
    NECESSARY = "NECESSARY"                      # Core change strictly required
    RELATED = "RELATED"                          # Callers/callees requiring coordinated update
    OPTIONAL = "OPTIONAL"                        # Non-critical enhancement or cleanup
    UNRELATED = "UNRELATED"                      # Scope creep - flagged for exclusion
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"      # High risk or breaking change needing user consent


@dataclass
class DependencyNode:
    """Represents a component, symbol, API, or test in the dependency graph."""
    id: str                                      # Unique canonical ID (e.g. "symbol:src/auth.py:login")
    name: str                                    # Human-readable name
    level: GraphLevel                            # Abstraction level
    file_path: Optional[str] = None              # Relative workspace file path
    line_number: Optional[int] = None            # Source line definition
    symbol_type: Optional[str] = None            # e.g., "function", "class", "endpoint", "table"
    is_public: bool = True                       # True if part of module's public interface
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "level": self.level.value,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "symbol_type": self.symbol_type,
            "is_public": self.is_public,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DependencyNode:
        return cls(
            id=data["id"],
            name=data["name"],
            level=GraphLevel(data["level"]),
            file_path=data.get("file_path"),
            line_number=data.get("line_number"),
            symbol_type=data.get("symbol_type"),
            is_public=data.get("is_public", True),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DependencyEdge:
    """Represents a directed relationship between two dependency graph nodes."""
    source_id: str                               # Node initiating relationship (e.g., caller, importer)
    target_id: str                               # Node being depended on (e.g., callee, imported)
    relationship: RelationshipType               # Type of relationship
    evidence_source: EvidenceSource = EvidenceSource.STATIC
    confidence: ConfidenceLevel = ConfidenceLevel.VERIFIED
    weight: float = 1.0                          # Coupling strength (0.0 to 1.0)
    is_runtime: bool = True                      # False if test-only or dev-only dependency
    is_optional: bool = False                    # True if dynamic or optional import
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship": self.relationship.value,
            "evidence_source": self.evidence_source.value,
            "confidence": self.confidence.value,
            "weight": self.weight,
            "is_runtime": self.is_runtime,
            "is_optional": self.is_optional,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DependencyEdge:
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            relationship=RelationshipType(data["relationship"]),
            evidence_source=EvidenceSource(data.get("evidence_source", "STATIC")),
            confidence=ConfidenceLevel(data.get("confidence", "VERIFIED")),
            weight=data.get("weight", 1.0),
            is_runtime=data.get("is_runtime", True),
            is_optional=data.get("is_optional", False),
            rationale=data.get("rationale", ""),
        )


@dataclass
class ImpactedComponent:
    """An affected downstream component discovered during impact propagation."""
    node: DependencyNode
    impact_type: str                             # DIRECT, INDIRECT, REGRESSION, SECURITY, API, DATA
    propagation_path: List[str]                  # Chain of node IDs from change to this component
    depth: int                                   # Hops away from the modified node
    risk: ImpactRisk                             # Risk tier of impact on this component
    confidence: ConfidenceLevel = ConfidenceLevel.VERIFIED
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node": self.node.to_dict(),
            "impact_type": self.impact_type,
            "propagation_path": self.propagation_path,
            "depth": self.depth,
            "risk": self.risk.value,
            "confidence": self.confidence.value,
            "rationale": self.rationale,
        }


@dataclass
class ChangeImpactReport:
    """
    Comprehensive, machine-readable report detailing the direct and indirect
    consequences of a proposed code change before any modification occurs.
    """
    task_id: str
    proposed_change_summary: str
    changed_files: List[str]
    changed_symbols: List[str]
    direct_dependents: List[ImpactedComponent] = field(default_factory=list)
    transitive_dependents: List[ImpactedComponent] = field(default_factory=list)
    affected_components: List[ImpactedComponent] = field(default_factory=list)
    affected_apis: List[Dict[str, Any]] = field(default_factory=list)
    affected_database_structures: List[Dict[str, Any]] = field(default_factory=list)
    affected_configuration: List[Dict[str, Any]] = field(default_factory=list)
    security_implications: List[Dict[str, Any]] = field(default_factory=list)
    architecture_implications: List[Dict[str, Any]] = field(default_factory=list)
    requirement_traceability: List[Dict[str, Any]] = field(default_factory=list)
    adr_traceability: List[Dict[str, Any]] = field(default_factory=list)
    public_contract_compatibility: ContractCompatibility = ContractCompatibility.BACKWARD_COMPATIBLE
    contract_compatibility_details: List[Dict[str, Any]] = field(default_factory=list)
    relevant_tests: List[Dict[str, Any]] = field(default_factory=list)
    missing_test_coverage: List[str] = field(default_factory=list)
    risk_classification: ImpactRisk = ImpactRisk.LOW
    risk_factors: List[str] = field(default_factory=list)
    uncertainties: List[str] = field(default_factory=list)
    recommended_implementation_scope: Dict[str, List[str]] = field(default_factory=dict)
    recommended_verification_plan: List[str] = field(default_factory=list)
    evidence_provenance: Dict[str, str] = field(default_factory=dict)
    generated_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "proposed_change_summary": self.proposed_change_summary,
            "changed_files": self.changed_files,
            "changed_symbols": self.changed_symbols,
            "direct_dependents": [d.to_dict() for d in self.direct_dependents],
            "transitive_dependents": [t.to_dict() for t in self.transitive_dependents],
            "affected_components": [a.to_dict() for a in self.affected_components],
            "affected_apis": self.affected_apis,
            "affected_database_structures": self.affected_database_structures,
            "affected_configuration": self.affected_configuration,
            "security_implications": self.security_implications,
            "architecture_implications": self.architecture_implications,
            "requirement_traceability": self.requirement_traceability,
            "adr_traceability": self.adr_traceability,
            "public_contract_compatibility": self.public_contract_compatibility.value,
            "contract_compatibility_details": self.contract_compatibility_details,
            "relevant_tests": self.relevant_tests,
            "missing_test_coverage": self.missing_test_coverage,
            "risk_classification": self.risk_classification.value,
            "risk_factors": self.risk_factors,
            "uncertainties": self.uncertainties,
            "recommended_implementation_scope": self.recommended_implementation_scope,
            "recommended_verification_plan": self.recommended_verification_plan,
            "evidence_provenance": self.evidence_provenance,
            "generated_timestamp": self.generated_timestamp,
        }


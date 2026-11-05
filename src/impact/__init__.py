"""
src/impact/__init__.py - Change Impact Analysis Subsystem Exports.

Phase 11.4: Change Impact Analysis.
"""

from src.impact.architecture_checker import ArchitectureRequirementImpactChecker
from src.impact.change_analyzers import ChangeSpecificAnalyzer
from src.impact.contract_compatibility import ContractCompatibilityAnalyzer
from src.impact.dynamic_analyzer import DynamicEvidenceAnalyzer
from src.impact.engine import ChangeImpactAnalysisEngine
from src.impact.graph import MultiLevelDependencyGraph
from src.impact.models import (
    ChangeImpactReport,
    ChangeScopeCategory,
    ConfidenceLevel,
    ContractCompatibility,
    DependencyEdge,
    DependencyNode,
    EvidenceSource,
    GraphLevel,
    ImpactRisk,
    ImpactedComponent,
    RelationshipType,
)
from src.impact.persistence import DependencyGraphPersistence
from src.impact.planner_integration import ImplementationScopeController
from src.impact.propagator import ImpactPropagator
from src.impact.risk_assessor import BlastRadiusRiskAssessor
from src.impact.static_analyzer import StaticDependencyAnalyzer
from src.impact.test_impact import TestImpactAnalyzer

__all__ = [
    "GraphLevel",
    "RelationshipType",
    "EvidenceSource",
    "ConfidenceLevel",
    "ImpactRisk",
    "ContractCompatibility",
    "ChangeScopeCategory",
    "DependencyNode",
    "DependencyEdge",
    "ImpactedComponent",
    "ChangeImpactReport",
    "MultiLevelDependencyGraph",
    "StaticDependencyAnalyzer",
    "DynamicEvidenceAnalyzer",
    "ImpactPropagator",
    "ChangeSpecificAnalyzer",
    "BlastRadiusRiskAssessor",
    "TestImpactAnalyzer",
    "ArchitectureRequirementImpactChecker",
    "ContractCompatibilityAnalyzer",
    "DependencyGraphPersistence",
    "ImplementationScopeController",
    "ChangeImpactAnalysisEngine",
]


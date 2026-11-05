"""
src/intelligence -- Project & Repository Intelligence Subsystem.

Phase 11.0: Project & Repository Intelligence.
Exports:
- ProjectKnowledge and related data models
- ConfidenceLevel (VERIFIED, INFERRED, UNKNOWN)
- RepositoryDiscoveryEngine
- ArchitectureMapper
- PersistentProjectIntelligenceManager
- ProjectIntelligenceRetriever
"""

from src.intelligence.models import (
    ApiEndpoint,
    ArchitectureMap,
    BuildCommands,
    ComponentNode,
    ConfidenceLevel,
    DatabaseSchemaInfo,
    EntryPoint,
    EvidenceFinding,
    FrameworkInfo,
    LanguageInfo,
    ProjectKnowledge,
    ProjectType,
)
from src.intelligence.discovery import (
    DEFAULT_SKIP_DIRS,
    SENSITIVE_FILES,
    RepositoryDiscoveryEngine,
)
from src.intelligence.architecture import (
    ArchitectureMapper,
)
from src.intelligence.persistence import (
    KNOWLEDGE_FILENAME,
    PersistentProjectIntelligenceManager,
)
from src.intelligence.agent_integration import (
    ProjectIntelligenceRetriever,
)
from src.intelligence.requirement_models import (
    ClarificationQuestion,
    ProjectSpecification,
    RequirementCategory,
    RequirementClassification,
    RequirementConflict,
    RequirementItem,
    RequirementPriority,
    RequirementRevision,
    RequirementStatus,
    TraceabilityLink,
    UnresolvedDecision,
    UserPersonaRole,
    UserWorkflow,
)
from src.intelligence.requirement_extractor import (
    ExtractedRequirementsBundle,
    RequirementExtractor,
)
from src.intelligence.requirement_classifier import (
    RequirementClassifier,
)
from src.intelligence.clarification import (
    ClarificationEngine,
)
from src.intelligence.conflict_detector import (
    ConflictDetector,
)
from src.intelligence.spec_generator import (
    SpecificationGenerator,
)
from src.intelligence.requirement_memory import (
    RequirementMemoryManager,
)
from src.intelligence.requirement_integration import (
    RequirementAnalysisResult,
    RequirementIntelligenceSystem,
)
from src.intelligence.architecture_models import (
    ArchitectureAlternative,
    ArchitectureBlueprint,
    ArchitectureDecisionRecord,
    ArchitectureDriver,
    ArchitecturePattern,
    ComplexityLevel,
    ComponentDesign,
    CostArchitectureEstimate,
    CostConfidence,
    DataArchitectureDesign,
    DecisionApprovalStatus,
    DriverCategory,
    MigrationPlan,
    NontechnicalExplanation,
    SecurityArchitectureDesign,
)
from src.intelligence.architecture_drivers import (
    ArchitectureDriverExtractor,
)
from src.intelligence.architecture_alternatives import (
    ArchitectureAlternativeEngine,
)
from src.intelligence.tech_stack_intelligence import (
    TechStackIntelligenceEngine,
)
from src.intelligence.data_and_security import (
    DataArchitectureAnalyzer,
    SecurityArchitectureAnalyzer,
)
from src.intelligence.adr_manager import (
    ADRManager,
)
from src.intelligence.blueprint_generator import (
    ArchitectureBlueprintGenerator,
)
from src.intelligence.architecture_integration import (
    ArchitectureIntelligenceSystem,
    ArchitectureSynthesisResult,
)

__all__ = [
    # Models
    "ConfidenceLevel",
    "EvidenceFinding",
    "ProjectType",
    "LanguageInfo",
    "FrameworkInfo",
    "BuildCommands",
    "EntryPoint",
    "ApiEndpoint",
    "DatabaseSchemaInfo",
    "ComponentNode",
    "ArchitectureMap",
    "ProjectKnowledge",

    # Discovery
    "DEFAULT_SKIP_DIRS",
    "SENSITIVE_FILES",
    "RepositoryDiscoveryEngine",

    # Architecture
    "ArchitectureMapper",

    # Persistence
    "KNOWLEDGE_FILENAME",
    "PersistentProjectIntelligenceManager",

    # Agent Integration
    "ProjectIntelligenceRetriever",

    # Phase 11.1 Requirement Models
    "RequirementClassification",
    "RequirementCategory",
    "RequirementPriority",
    "RequirementStatus",
    "RequirementItem",
    "UserPersonaRole",
    "UserWorkflow",
    "ClarificationQuestion",
    "UnresolvedDecision",
    "RequirementConflict",
    "TraceabilityLink",
    "RequirementRevision",
    "ProjectSpecification",

    # Phase 11.1 Engines & Systems
    "RequirementExtractor",
    "ExtractedRequirementsBundle",
    "RequirementClassifier",
    "ClarificationEngine",
    "ConflictDetector",
    "SpecificationGenerator",
    "RequirementMemoryManager",
    "RequirementIntelligenceSystem",
    "RequirementAnalysisResult",

    # Phase 11.2 Architecture Models
    "ArchitecturePattern",
    "DecisionApprovalStatus",
    "DriverCategory",
    "CostConfidence",
    "ComplexityLevel",
    "ArchitectureDriver",
    "ArchitectureAlternative",
    "ArchitectureDecisionRecord",
    "ComponentDesign",
    "DataArchitectureDesign",
    "SecurityArchitectureDesign",
    "CostArchitectureEstimate",
    "MigrationPlan",
    "NontechnicalExplanation",
    "ArchitectureBlueprint",

    # Phase 11.2 Engines & Systems
    "ArchitectureDriverExtractor",
    "ArchitectureAlternativeEngine",
    "TechStackIntelligenceEngine",
    "DataArchitectureAnalyzer",
    "SecurityArchitectureAnalyzer",
    "ADRManager",
    "ArchitectureBlueprintGenerator",
    "ArchitectureIntelligenceSystem",
    "ArchitectureSynthesisResult",
]


"""
test_phase_11_2_architecture_intelligence.py -- Phase 11.2 Deterministic Verification Suite.

Validates all 27 scenarios defined in Phase 11.2:
1. Simple application architecture selection
2. Complex SaaS architecture selection
3. Explicit monolith constraint preservation
4. Explicit modular monolith constraint preservation
5. Explicit technology preservation
6. Existing repository compatibility
7. Architecture alternative evaluation
8. Overengineering prevention
9. Underengineering detection
10. Quality attribute analysis
11. Database architecture decisions
12. Security architecture analysis
13. Dependency compatibility
14. Cost estimation uncertainty
15. Architecture decision record creation
16. Approval-state enforcement
17. Architecture revision history
18. Requirement-to-architecture traceability
19. Existing architecture migration planning
20. Rollback strategy generation
21. Conflicting technical requirements
22. Insufficient evidence handling
23. Nontechnical explanations
24. Malformed model output handling
25. Workspace and tenant isolation
26. Agent planner integration
27. Existing functionality regression
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src.intelligence.adr_manager import ADRManager
from src.intelligence.architecture_alternatives import ArchitectureAlternativeEngine
from src.intelligence.architecture_drivers import ArchitectureDriverExtractor
from src.intelligence.architecture_integration import (
    ArchitectureIntelligenceSystem,
    ArchitectureSynthesisResult,
)
from src.intelligence.architecture_models import (
    ArchitectureAlternative,
    ArchitectureBlueprint,
    ArchitectureDecisionRecord,
    ArchitectureDriver,
    ArchitecturePattern,
    CostConfidence,
    DecisionApprovalStatus,
    DriverCategory,
    MigrationPlan,
    NontechnicalExplanation,
)
from src.intelligence.blueprint_generator import ArchitectureBlueprintGenerator
from src.intelligence.models import (
    BuildCommands,
    ConfidenceLevel,
    EvidenceFinding,
    FrameworkInfo,
    LanguageInfo,
    ProjectKnowledge,
    ProjectType,
)
from src.intelligence.persistence import PersistentProjectIntelligenceManager
from src.intelligence.requirement_integration import RequirementIntelligenceSystem
from src.intelligence.requirement_memory import RequirementMemoryManager
from src.intelligence.requirement_models import (
    ProjectSpecification,
    RequirementCategory,
    RequirementClassification,
    RequirementItem,
    RequirementPriority,
    RequirementStatus,
)


class TestPhase112ArchitectureIntelligence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="crusor_p11_2_")
        self.workspace = Path(self.tmp_dir) / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.req_system = RequirementIntelligenceSystem()
        self.arch_system = ArchitectureIntelligenceSystem()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _prepare_spec(self, prompt: str, task_id: str, tenant_id: str = "default_tenant") -> ProjectSpecification:
        res = self.req_system.analyze_request(prompt, str(self.workspace), task_id=task_id, tenant_id=tenant_id)
        return res.specification

    # 1. Simple application architecture selection
    def test_01_simple_application_architecture_selection(self) -> None:
        prompt = "Build a personal expense tracker."
        self._prepare_spec(prompt, "t1")
        res = self.arch_system.synthesize_architecture("t1", str(self.workspace))
        # Should select Monolith or Modular Monolith, not Microservices
        self.assertIn(res.blueprint.architecture_style, {ArchitecturePattern.MONOLITH, ArchitecturePattern.MODULAR_MONOLITH})
        self.assertNotEqual(res.blueprint.architecture_style, ArchitecturePattern.MICROSERVICES)

    # 2. Complex SaaS architecture selection
    def test_02_complex_saas_architecture_selection(self) -> None:
        prompt = "Build a multi-tenant SaaS platform with subscriptions, teams, authentication, and analytics."
        self._prepare_spec(prompt, "t2")
        res = self.arch_system.synthesize_architecture("t2", str(self.workspace))
        # Should select Modular Monolith with bounded contexts, not simple monolith
        self.assertEqual(res.blueprint.architecture_style, ArchitecturePattern.MODULAR_MONOLITH)
        self.assertIn("tenant_id", res.blueprint.database_architecture.tenant_isolation_strategy)

    # 3. Explicit monolith constraint preservation
    def test_03_explicit_monolith_constraint_preservation(self) -> None:
        prompt = "Build a student grading portal. Follow a monolith architecture."
        self._prepare_spec(prompt, "t3")
        res = self.arch_system.synthesize_architecture("t3", str(self.workspace))
        self.assertEqual(res.blueprint.architecture_style, ArchitecturePattern.MONOLITH)
        # Microservices must be eliminated
        micro = next((a for a in res.all_alternatives if a.pattern == ArchitecturePattern.MICROSERVICES), None)
        if micro:
            self.assertFalse(micro.is_viable)

    # 4. Explicit modular monolith constraint preservation
    def test_04_explicit_modular_monolith_constraint_preservation(self) -> None:
        prompt = "Build an ecommerce application using Next.js, FastAPI, PostgreSQL, Redis, and a modular monolith architecture."
        self._prepare_spec(prompt, "t4")
        res = self.arch_system.synthesize_architecture("t4", str(self.workspace))
        self.assertEqual(res.blueprint.architecture_style, ArchitecturePattern.MODULAR_MONOLITH)
        self.assertTrue(res.selected_alternative.is_viable)

    # 5. Explicit technology preservation
    def test_05_explicit_technology_preservation(self) -> None:
        prompt = "Build an application using Next.js, FastAPI, PostgreSQL, and Redis."
        self._prepare_spec(prompt, "t5")
        res = self.arch_system.synthesize_architecture("t5", str(self.workspace))
        stack = res.blueprint.technology_stack
        self.assertIn("FastAPI", stack.get("backend", ""))
        self.assertIn("Next.js", stack.get("frontend", ""))
        self.assertIn("PostgreSQL", stack.get("database", ""))
        self.assertIn("Redis", stack.get("cache", ""))

    # 6. Existing repository compatibility
    def test_06_existing_repository_compatibility(self) -> None:
        pyproject = self.workspace / "pyproject.toml"
        pyproject.write_text(
            '[tool.poetry]\nname = "inventory-service"\nversion = "1.0"\n'
            '[tool.poetry.dependencies]\npython = "^3.11"\nfastapi = "^0.110.0"\n',
            encoding="utf-8",
        )
        (self.workspace / "main.py").write_text("import fastapi\napp = fastapi.FastAPI()\n", encoding="utf-8")

        prompt = "Add an order processing system."
        self._prepare_spec(prompt, "t6")
        res = self.arch_system.synthesize_architecture("t6", str(self.workspace), force_rescan=True)
        # Should reuse FastAPI from repo
        self.assertIn("FastAPI", res.blueprint.technology_stack.get("backend", ""))

    # 7. Architecture alternative evaluation
    def test_07_architecture_alternative_evaluation(self) -> None:
        prompt = "Build an ecommerce store."
        self._prepare_spec(prompt, "t7")
        res = self.arch_system.synthesize_architecture("t7", str(self.workspace))
        self.assertTrue(len(res.all_alternatives) >= 3)
        for alt in res.all_alternatives:
            self.assertTrue(len(alt.advantages) > 0)
            self.assertTrue(len(alt.disadvantages) > 0)

    # 8. Overengineering prevention
    def test_08_overengineering_prevention(self) -> None:
        prompt = "Create a simple CLI calculator utility."
        self._prepare_spec(prompt, "t8")
        res = self.arch_system.synthesize_architecture("t8", str(self.workspace))
        # Microservices must be marked non-viable for simple CLI utility
        micro = next((a for a in res.all_alternatives if a.pattern == ArchitecturePattern.MICROSERVICES), None)
        self.assertIsNotNone(micro)
        self.assertFalse(micro.is_viable)
        self.assertIn("Overengineering prevention", micro.elimination_reason)

    # 9. Underengineering detection
    def test_09_underengineering_detection(self) -> None:
        prompt = "Build a multi-tenant enterprise SaaS platform with teams, billing, and organizations."
        self._prepare_spec(prompt, "t9")
        res = self.arch_system.synthesize_architecture("t9", str(self.workspace))
        mono = next((a for a in res.all_alternatives if a.pattern == ArchitecturePattern.MONOLITH), None)
        self.assertIsNotNone(mono)
        self.assertFalse(mono.is_viable)
        self.assertIn("Underengineering prevention", mono.elimination_reason)

    # 10. Quality attribute analysis
    def test_10_quality_attribute_analysis(self) -> None:
        prompt = "Build a high-performance banking transaction API with strict security."
        self._prepare_spec(prompt, "t10")
        res = self.arch_system.synthesize_architecture("t10", str(self.workspace))
        qa_drivers = [d for d in res.drivers if d.category == DriverCategory.QUALITY_ATTRIBUTE]
        self.assertTrue(len(qa_drivers) >= 2)
        self.assertTrue(any("security" in d.name.lower() for d in qa_drivers))

    # 11. Database architecture decisions
    def test_11_database_architecture_decisions(self) -> None:
        prompt = "Build an accounting application."
        self._prepare_spec(prompt, "t11")
        res = self.arch_system.synthesize_architecture("t11", str(self.workspace))
        db_arch = res.blueprint.database_architecture
        self.assertIn("ACID", db_arch.transaction_strategy)
        self.assertTrue(len(db_arch.entities) > 0)

    # 12. Security architecture analysis
    def test_12_security_architecture_analysis(self) -> None:
        prompt = "Build a healthcare patient portal."
        self._prepare_spec(prompt, "t12")
        res = self.arch_system.synthesize_architecture("t12", str(self.workspace))
        sec_arch = res.blueprint.security_architecture
        self.assertIn("RBAC", sec_arch.authorization_model)
        self.assertIn("Zero secrets", sec_arch.secret_management)

    # 13. Dependency compatibility
    def test_13_dependency_compatibility(self) -> None:
        prompt = "Build using Next.js and FastAPI."
        self._prepare_spec(prompt, "t13")
        res = self.arch_system.synthesize_architecture("t13", str(self.workspace))
        stack = res.blueprint.technology_stack
        self.assertEqual(stack.get("frontend"), "Next.js")
        self.assertEqual(stack.get("backend"), "FastAPI")

    # 14. Cost estimation uncertainty
    def test_14_cost_estimation_uncertainty(self) -> None:
        # Simple app
        self._prepare_spec("Build a simple personal expense tracker", "t14_simple")
        res_simple = self.arch_system.synthesize_architecture("t14_simple", str(self.workspace))
        self.assertEqual(res_simple.blueprint.cost_considerations.cost_confidence, CostConfidence.VERIFIED)
        self.assertEqual(res_simple.blueprint.cost_considerations.total_estimated_monthly_usd, 0.0)

        # SaaS app
        self._prepare_spec("Build a multi-tenant SaaS platform with billing", "t14_saas")
        res_saas = self.arch_system.synthesize_architecture("t14_saas", str(self.workspace))
        self.assertEqual(res_saas.blueprint.cost_considerations.cost_confidence, CostConfidence.ESTIMATED)
        self.assertTrue(res_saas.blueprint.cost_considerations.total_estimated_monthly_usd > 0.0)

    # 15. Architecture decision record creation
    def test_15_architecture_decision_record_creation(self) -> None:
        prompt = "Build an ecommerce store."
        self._prepare_spec(prompt, "t15")
        res = self.arch_system.synthesize_architecture("t15", str(self.workspace))
        adr_ids = [a.id for a in res.adrs]
        self.assertIn("ADR-001", adr_ids)
        self.assertIn("ADR-002", adr_ids)
        self.assertIn("ADR-003", adr_ids)

    # 16. Approval-state enforcement
    def test_16_approval_state_enforcement(self) -> None:
        prompt = "Build a general utility app."
        self._prepare_spec(prompt, "t16")
        res = self.arch_system.synthesize_architecture("t16", str(self.workspace))
        # Non-explicit decisions start as PROPOSED
        adr3 = next(a for a in res.adrs if a.id == "ADR-003")
        self.assertEqual(adr3.approval_status, DecisionApprovalStatus.PROPOSED)

    # 17. Architecture revision history
    def test_17_architecture_revision_history(self) -> None:
        prompt = "Build a blog CMS."
        self._prepare_spec(prompt, "t17")
        self.arch_system.synthesize_architecture("t17", str(self.workspace))
        # Approve ADR-003
        updated = self.arch_system.approve_adr("t17", "ADR-003", str(self.workspace), author="lead_architect")
        self.assertEqual(updated.approval_status, DecisionApprovalStatus.APPROVED)
        self.assertEqual(updated.version, 2)
        self.assertEqual(len(updated.revision_history), 1)

    # 18. Requirement-to-architecture traceability
    def test_18_requirement_to_architecture_traceability(self) -> None:
        prompt = "Build a todo app."
        self._prepare_spec(prompt, "t18")
        res = self.arch_system.synthesize_architecture("t18", str(self.workspace))
        self.assertTrue(len(res.blueprint.traceability_matrix) > 0)
        for req_id, targets in res.blueprint.traceability_matrix.items():
            self.assertTrue(any("component:" in t for t in targets))
            self.assertTrue(any("adr:" in t for t in targets))

    # 19. Existing architecture migration planning
    def test_19_existing_architecture_migration_planning(self) -> None:
        pyproject = self.workspace / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "shop"\nversion = "1.0"\n[tool.poetry.dependencies]\npython = "^3.10"\nfastapi = "^0.110.0"\n', encoding="utf-8")
        self._prepare_spec("Add a checkout module", "t19")
        res = self.arch_system.synthesize_architecture("t19", str(self.workspace), force_rescan=True)
        self.assertTrue(res.blueprint.migration_plan.is_migration_needed)
        self.assertTrue(len(res.blueprint.migration_plan.migration_order) >= 3)

    # 20. Rollback strategy generation
    def test_20_rollback_strategy_generation(self) -> None:
        pyproject = self.workspace / "pyproject.toml"
        pyproject.write_text('[tool.poetry]\nname = "shop"\nversion = "1.0"\n[tool.poetry.dependencies]\npython = "^3.10"\nfastapi = "^0.110.0"\n', encoding="utf-8")
        self._prepare_spec("Add checkout", "t20")
        res = self.arch_system.synthesize_architecture("t20", str(self.workspace), force_rescan=True)
        self.assertIn("Git branch reversal", res.blueprint.migration_plan.rollback_strategy)

    # 21. Conflicting technical requirements
    def test_21_conflicting_technical_requirements(self) -> None:
        spec = self._prepare_spec("Build a static client with postgresql", "t21")
        # Spec has conflicts
        self.assertTrue(len(spec.conflicts) > 0)
        res = self.arch_system.synthesize_architecture("t21", str(self.workspace))
        self.assertTrue(len(res.blueprint.known_risks) > 0)

    # 22. Insufficient evidence handling
    def test_22_insufficient_evidence_handling(self) -> None:
        self._prepare_spec("Build an app", "t22")
        res = self.arch_system.synthesize_architecture("t22", str(self.workspace))
        self.assertIsNotNone(res.blueprint.cost_considerations.cost_confidence)

    # 23. Nontechnical explanations
    def test_23_nontechnical_explanations(self) -> None:
        self._prepare_spec("Build an Amazon-like store for startup", "t23")
        res = self.arch_system.synthesize_architecture("t23", str(self.workspace))
        nontech = res.blueprint.nontechnical_explanation
        self.assertIsNotNone(nontech)
        self.assertTrue(len(nontech.simple_summary) > 20)
        self.assertTrue(len(nontech.main_advantages) >= 2)

    # 24. Malformed model output handling
    def test_24_malformed_model_output_handling(self) -> None:
        self._prepare_spec("$$%%^^&&**!!@@", "t24")
        res = self.arch_system.synthesize_architecture("t24", str(self.workspace))
        self.assertIsNotNone(res.blueprint)
        self.assertTrue(len(res.blueprint.components) > 0)

    # 25. Workspace and tenant isolation
    def test_25_workspace_and_tenant_isolation(self) -> None:
        self._prepare_spec("Tenant Alpha store", "t25", tenant_id="tenant_alpha")
        self._prepare_spec("Tenant Beta portal", "t25", tenant_id="tenant_beta")

        res_a = self.arch_system.synthesize_architecture("t25", str(self.workspace), tenant_id="tenant_alpha")
        res_b = self.arch_system.synthesize_architecture("t25", str(self.workspace), tenant_id="tenant_beta")

        mgr_a = ADRManager(str(self.workspace), tenant_id="tenant_alpha")
        mgr_b = ADRManager(str(self.workspace), tenant_id="tenant_beta")

        self.assertEqual(len(mgr_a.list_adrs()), 3)
        self.assertEqual(len(mgr_b.list_adrs()), 3)

        # Check blueprints isolated
        bp_a = self.arch_system.load_blueprint("t25", str(self.workspace), tenant_id="tenant_alpha")
        bp_b = self.arch_system.load_blueprint("t25", str(self.workspace), tenant_id="tenant_beta")
        self.assertIn("Alpha", bp_a.architecture_overview)
        self.assertIn("Beta", bp_b.architecture_overview)

    # 26. Agent planner integration
    def test_26_agent_planner_integration(self) -> None:
        self._prepare_spec("Build a SaaS app", "t26")
        self.arch_system.synthesize_architecture("t26", str(self.workspace))
        ctx = self.arch_system.get_planner_architecture_context("t26", str(self.workspace))
        self.assertIn("=== APPROVED ARCHITECTURE BLUEPRINT ===", ctx)
        self.assertIn("MODULAR_MONOLITH", ctx)

        # Deviation validation
        bp = self.arch_system.load_blueprint("t26", str(self.workspace))
        valid, devs = self.arch_system.validate_plan_against_blueprint(bp, ["Create 5 separate microservices with gRPC"])
        self.assertFalse(valid)
        self.assertTrue(len(devs) > 0)

    # 27. Existing functionality regression
    def test_27_existing_functionality_regression(self) -> None:
        # Phase 11.0 and 11.1 regression check
        kmgr = PersistentProjectIntelligenceManager(str(self.workspace))
        k = kmgr.get_project_knowledge()
        self.assertIsNotNone(k)

        spec = self._prepare_spec("Build a customer portal", "t27")
        self.assertIsNotNone(spec)
        self.assertTrue(len(spec.all_requirements()) > 0)


if __name__ == "__main__":
    unittest.main()

"""
test_phase_11_1_requirement_understanding.py -- Phase 11.1 Deterministic Verification Suite.

Validates all 23 scenarios defined in Phase 11.1:
1. Simple natural-language requests
2. Complex product requests
3. Technical user instructions
4. Nontechnical user instructions
5. Explicit technology constraints
6. Missing business requirements
7. Discoverable repository requirements
8. Reasonable technical defaults
9. Essential clarification detection
10. Unnecessary-question suppression
11. Contradiction detection
12. Ambiguity detection
13. Requirement prioritization
14. Acceptance criteria generation
15. Requirement traceability
16. Requirement revision history
17. Workspace isolation
18. Tenant isolation
19. Context persistence and recovery
20. Integration with Phase 11.0
21. Malformed model output handling
22. Scope-change detection
23. Existing functionality regression
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src.intelligence.clarification import ClarificationEngine
from src.intelligence.conflict_detector import ConflictDetector
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
from src.intelligence.requirement_classifier import RequirementClassifier
from src.intelligence.requirement_extractor import RequirementExtractor
from src.intelligence.requirement_integration import (
    RequirementAnalysisResult,
    RequirementIntelligenceSystem,
)
from src.intelligence.requirement_memory import RequirementMemoryManager
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
from src.intelligence.spec_generator import SpecificationGenerator


class TestPhase111RequirementUnderstanding(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="crusor_p11_1_")
        self.workspace = Path(self.tmp_dir) / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.system = RequirementIntelligenceSystem()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Simple natural-language requests
    def test_01_simple_natural_language_requests(self) -> None:
        prompt = "Create a Python script to convert markdown files to PDF"
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t1")
        self.assertEqual(res.communication_style, "NON_TECHNICAL")
        self.assertTrue(len(res.specification.all_requirements()) > 0)
        self.assertIn("markdown", res.specification.problem_statement.lower())

    # 2. Complex product requests
    def test_02_complex_product_requests(self) -> None:
        prompt = "Build an Amazon-like ecommerce website for my startup."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t2")
        self.assertEqual(res.communication_style, "NON_TECHNICAL")
        self.assertTrue(any("cart" in r.description.lower() for r in res.specification.functional_requirements))
        self.assertTrue(any("catalog" in r.description.lower() for r in res.specification.functional_requirements))
        self.assertTrue(len(res.specification.user_workflows) > 0)
        self.assertTrue(len(res.specification.user_personas) >= 2)

    # 3. Technical user instructions
    def test_03_technical_user_instructions(self) -> None:
        prompt = (
            "Build an ecommerce application using Next.js, FastAPI, PostgreSQL, Redis, and JWT authentication. "
            "Follow a modular monolith architecture."
        )
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t3")
        self.assertEqual(res.communication_style, "TECHNICAL")
        tech_descs = [r.description.lower() for r in res.specification.technical_constraints]
        self.assertTrue(any("next.js" in td for td in tech_descs))
        self.assertTrue(any("fastapi" in td for td in tech_descs))
        self.assertTrue(any("postgresql" in td for td in tech_descs))
        self.assertTrue(any("redis" in td for td in tech_descs))
        self.assertTrue(any("jwt" in td for td in tech_descs))
        self.assertTrue(any("modular monolith" in td for td in tech_descs))

    # 4. Nontechnical user instructions
    def test_04_nontechnical_user_instructions(self) -> None:
        prompt = "I need an online booking system for a hair salon so customers can book appointments."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t4")
        self.assertEqual(res.communication_style, "NON_TECHNICAL")
        self.assertTrue(res.specification.desired_outcome != "")
        self.assertTrue(len(res.specification.assumptions_and_defaults) > 0)

    # 5. Explicit technology constraints
    def test_05_explicit_technology_constraints(self) -> None:
        prompt = "Build a customer feedback dashboard using React and Flask with SQLite."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t5")
        for tc in res.specification.technical_constraints:
            self.assertEqual(tc.classification, RequirementClassification.EXPLICIT)
            self.assertEqual(tc.status, RequirementStatus.ACCEPTED)
            self.assertIn("Direct user prompt constraint", tc.evidence_source)

    # 6. Missing business requirements
    def test_06_missing_business_requirements(self) -> None:
        prompt = "Build an ecommerce store."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t6")
        topics = [q.rationale.lower() for q in res.clarification_questions]
        self.assertTrue(any("marketplace" in t or "vendor" in t or "payment" in t for t in topics))

    # 7. Discoverable repository requirements
    def test_07_discoverable_repository_requirements(self) -> None:
        # Prepopulate workspace with FastAPI pyproject.toml
        pyproject = self.workspace / "pyproject.toml"
        pyproject.write_text(
            '[tool.poetry]\nname = "existing-api"\nversion = "1.0"\n'
            '[tool.poetry.dependencies]\npython = "^3.11"\nfastapi = "^0.110.0"\npytest = "^8.0.0"\n',
            encoding="utf-8",
        )
        (self.workspace / "main.py").write_text("import fastapi\napp = fastapi.FastAPI()\n", encoding="utf-8")

        prompt = "Add an endpoint to process user payments with Stripe"
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t7", force_rescan=True)
        # Check if FastAPI is recognized as discoverable rather than asking
        disc = [r for r in res.specification.all_requirements() if r.classification == RequirementClassification.DISCOVERABLE]
        self.assertTrue(len(disc) > 0)
        self.assertTrue(any("fastapi" in d.evidence_source.lower() for d in disc))

    # 8. Reasonable technical defaults
    def test_08_reasonable_technical_defaults(self) -> None:
        prompt = "Build a user management microservice."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t8")
        defaults = [r for r in res.specification.all_requirements() if r.classification == RequirementClassification.REASONABLE_DEFAULT]
        self.assertTrue(len(defaults) >= 2)
        # Security & testing defaults must be present
        self.assertTrue(any("security" in d.description.lower() or "credential" in d.description.lower() for d in defaults))
        self.assertTrue(any("test" in d.description.lower() for d in defaults))

    # 9. Essential clarification detection
    def test_09_essential_clarification_detection(self) -> None:
        prompt = "Build an ecommerce website."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t9")
        self.assertTrue(len(res.clarification_questions) > 0)
        for q in res.clarification_questions:
            self.assertTrue(len(q.rationale) > 10)
            self.assertIsNotNone(q.default_choice)

    # 10. Unnecessary-question suppression
    def test_10_unnecessary_question_suppression(self) -> None:
        clarifier = ClarificationEngine()
        forbidden_questions = [
            ("Functions", "Should I use functions to structure the code?", ["Yes", "No"]),
            ("Components", "Should I create components for the UI?", ["Yes", "No"]),
            ("Service Layer", "Should I use a service layer pattern in backend?", ["Yes", "No"]),
        ]
        questions, _ = clarifier.evaluate_clarifications(forbidden_questions, [])
        self.assertEqual(len(questions), 0, "Micro-implementation questions must be suppressed!")

    # 11. Contradiction detection
    def test_11_contradiction_detection(self) -> None:
        prompt = "Build a purely static client-only site with a PostgreSQL database and backend server."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t11")
        self.assertTrue(len(res.conflicts) > 0)
        self.assertIn("Static-only client architecture contradicts server-side database", res.conflicts[0].conflict_description)
        self.assertFalse(res.is_ready_for_planning)

    # 12. Ambiguity detection
    def test_12_ambiguity_detection(self) -> None:
        detector = ConflictDetector()
        reqs = [
            RequirementItem(
                id="REQ-001",
                description="General business app",
                category=RequirementCategory.FUNCTIONAL,
                classification=RequirementClassification.REASONABLE_DEFAULT,
                acceptance_criteria=[],
            )
        ]
        conflicts, warnings, score, is_comp = detector.analyze(reqs, [], [])
        self.assertTrue(len(warnings) > 0)
        self.assertFalse(is_comp)

    # 13. Requirement prioritization
    def test_13_requirement_prioritization(self) -> None:
        prompt = "Build an ecommerce app with secure checkout and high-availability architecture."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t13")
        priorities = {r.priority for r in res.specification.all_requirements()}
        self.assertIn(RequirementPriority.CRITICAL, priorities)
        self.assertIn(RequirementPriority.HIGH, priorities)

    # 14. Acceptance criteria generation
    def test_14_acceptance_criteria_generation(self) -> None:
        prompt = "Create a user registration and login service."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t14")
        self.assertTrue(len(res.specification.acceptance_criteria) > 0)
        for req in res.specification.functional_requirements:
            self.assertTrue(len(req.acceptance_criteria) > 0)

    # 15. Requirement traceability
    def test_15_requirement_traceability(self) -> None:
        prompt = "Implement a calculator library."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t15")
        spec = res.specification
        gen = SpecificationGenerator(str(self.workspace))
        req_id = spec.functional_requirements[0].id
        gen.link_task_to_requirements(spec, task_id="TASK-1", requirement_ids=[req_id], components=["src/calc"])
        gen.record_verification(spec, requirement_id=req_id, test_id="test_calc_add", passed=True, files=["src/calc.py"])

        link = spec.traceability[req_id]
        self.assertIn("TASK-1", link.task_ids)
        self.assertIn("src/calc", link.architecture_components)
        self.assertIn("src/calc.py", link.modified_files)
        self.assertEqual(link.verification_status, "VERIFIED")

    # 16. Requirement revision history
    def test_16_requirement_revision_history(self) -> None:
        mem = RequirementMemoryManager(str(self.workspace))
        prompt = "Build a todo app."
        res = self.system.analyze_request(prompt, str(self.workspace), task_id="t16")
        spec = res.specification
        self.assertEqual(spec.version, 1)

        # Revise
        new_reqs = list(spec.all_requirements())
        new_reqs.append(
            RequirementItem(
                id="REQ-999",
                description="Add export to CSV",
                category=RequirementCategory.FUNCTIONAL,
                classification=RequirementClassification.EXPLICIT,
            )
        )
        revised_spec, scope_changes = mem.revise_specification(
            "t16", spec, "User requested CSV export", new_reqs
        )
        self.assertEqual(revised_spec.version, 2)
        self.assertEqual(len(revised_spec.revision_history), 2)
        self.assertTrue(any("REQ-999" in sc or "export" in sc.lower() for sc in scope_changes))

    # 17. Workspace isolation
    def test_17_workspace_isolation(self) -> None:
        ws_a = Path(self.tmp_dir) / "ws_a"
        ws_b = Path(self.tmp_dir) / "ws_b"
        ws_a.mkdir()
        ws_b.mkdir()

        res_a = self.system.analyze_request("Ecommerce store with Stripe", str(ws_a), task_id="task_shared")
        res_b = self.system.analyze_request("Blogging CMS with Markdown", str(ws_b), task_id="task_shared")

        mem_a = RequirementMemoryManager(str(ws_a))
        mem_b = RequirementMemoryManager(str(ws_b))

        spec_a = mem_a.load_specification("task_shared")
        spec_b = mem_b.load_specification("task_shared")

        self.assertIn("ecommerce", spec_a.desired_outcome.lower())
        self.assertIn("blogging", spec_b.desired_outcome.lower())
        self.assertNotIn("stripe", json.dumps(spec_b.to_dict()).lower())

    # 18. Tenant isolation
    def test_18_tenant_isolation(self) -> None:
        mem_t1 = RequirementMemoryManager(str(self.workspace), tenant_id="tenant_alpha")
        mem_t2 = RequirementMemoryManager(str(self.workspace), tenant_id="tenant_beta")

        res1 = self.system.analyze_request("Alpha private project", str(self.workspace), task_id="p1", tenant_id="tenant_alpha")
        res2 = self.system.analyze_request("Beta secret platform", str(self.workspace), task_id="p1", tenant_id="tenant_beta")

        spec1 = mem_t1.load_specification("p1")
        spec2 = mem_t2.load_specification("p1")

        self.assertIn("Alpha", spec1.problem_statement)
        self.assertIn("Beta", spec2.problem_statement)
        self.assertNotIn("Alpha", spec2.problem_statement)

    # 19. Context persistence and recovery
    def test_19_context_persistence_and_recovery(self) -> None:
        res = self.system.analyze_request("Persistent task test", str(self.workspace), task_id="t19")
        mem = RequirementMemoryManager(str(self.workspace))
        loaded = mem.load_specification("t19")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.spec_id, res.specification.spec_id)
        self.assertEqual(loaded.version, res.specification.version)

    # 20. Integration with Phase 11.0
    def test_20_integration_with_phase_11_0(self) -> None:
        context_str = self.system.get_planning_prompt_context("t2", str(self.workspace))
        # When specification exists
        res = self.system.analyze_request("Build an API service", str(self.workspace), task_id="t20")
        ctx = self.system.get_planning_prompt_context("t20", str(self.workspace))
        self.assertIn("=== APPROVED PROJECT SPECIFICATION", ctx)
        self.assertIn("Mandated Technical Constraints", ctx)

    # 21. Malformed model output handling
    def test_21_malformed_model_output_handling(self) -> None:
        # Edge cases: empty prompt, symbols, huge whitespace
        for malformed in ["", "   \n\n\t  ", "$$%%^^&&**!!@@", "a" * 1000]:
            res = self.system.analyze_request(malformed, str(self.workspace), task_id="t21")
            self.assertIsNotNone(res.specification)
            self.assertTrue(isinstance(res.summary_markdown, str))

    # 22. Scope-change detection
    def test_22_scope_change_detection(self) -> None:
        res = self.system.analyze_request("Create a weather forecast CLI tool", str(self.workspace), task_id="t22")
        spec = res.specification
        mem = RequirementMemoryManager(str(self.workspace))

        # User adds an unexpected mobile app requirement
        new_reqs = list(spec.all_requirements())
        new_reqs.append(
            RequirementItem(
                id="REQ-ADD",
                description="Also build native iOS and Android mobile app",
                category=RequirementCategory.FUNCTIONAL,
                classification=RequirementClassification.EXPLICIT,
                priority=RequirementPriority.HIGH,
            )
        )
        _, changes = mem.revise_specification("t22", spec, "Expanded scope with mobile app", new_reqs)
        self.assertTrue(any("Added" in c and "mobile" in c.lower() for c in changes))

    # 23. Existing functionality regression
    def test_23_existing_functionality_regression(self) -> None:
        # Verify Phase 11.0 intelligence retriever still operates cleanly
        from src.intelligence.agent_integration import ProjectIntelligenceRetriever
        mgr = PersistentProjectIntelligenceManager(str(self.workspace))
        retriever = ProjectIntelligenceRetriever(mgr)
        summary = retriever.render_markdown_context()
        self.assertTrue("Project Intelligence" in summary)


if __name__ == "__main__":
    unittest.main()


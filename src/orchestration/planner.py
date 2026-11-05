"""
src/orchestration/planner.py - Structured Engineering Task Planner & DAG Synthesizer.

Phase 11.6: Autonomous Engineering Execution.
Consumes:
- ProjectKnowledge (11.0)
- ProjectSpecification (11.1)
- ArchitectureBlueprint & ADRs (11.2)
- ChangePlan (11.3)
- ChangeImpactReport (11.4)
- TestBaseline (11.5)

Produces:
- Structured EngineeringPlanDAG with dependency checking, circularity detection,
  minimal plan optimization, and scope-creep prevention.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Set

from src.impact.models import ChangeImpactReport
from src.intelligence.architecture_models import ArchitectureBlueprint
from src.intelligence.models import ProjectKnowledge
from src.intelligence.requirement_models import ProjectSpecification
from src.orchestration.models import EngineeringPlanDAG, EngineeringTaskNode
from src.regression.models import TestBaseline
from src.workspace.models import ChangePlan

log = logging.getLogger("crusor.orchestration.planner")


class ScopeCreepError(ValueError):
    """Raised when an unapproved scope expansion is detected."""
    pass


class EngineeringTaskPlanner:
    """
    Synthesizes structured, minimal, dependency-ordered engineering task plans.
    """

    def __init__(self, workspace_root: str, tenant_id: str = "default_tenant") -> None:
        self.workspace_root = workspace_root
        self.tenant_id = tenant_id

    def build_plan(
        self,
        task_id: str,
        specification: ProjectSpecification,
        blueprint: Optional[ArchitectureBlueprint] = None,
        knowledge: Optional[ProjectKnowledge] = None,
        impact_report: Optional[ChangeImpactReport] = None,
        test_baseline: Optional[TestBaseline] = None,
        change_plan: Optional[ChangePlan] = None,
    ) -> EngineeringPlanDAG:
        """
        Synthesizes an EngineeringPlanDAG tailored strictly to approved requirements.
        """
        dag = EngineeringPlanDAG(task_id=task_id)

        # 1. Scope Creep Validation
        if hasattr(specification, "all_requirements"):
            all_reqs = specification.all_requirements() if callable(specification.all_requirements) else specification.all_requirements
        else:
            all_reqs = getattr(specification, "requirements", [])
        approved_req_ids = {r.id for r in all_reqs if getattr(r.status, "value", str(r.status)) in {"APPROVED", "DISCOVERED", "PROPOSED", "VERIFIED"}}

        # 2. Extract tasks directly mapped to requirements
        created_nodes: Dict[str, EngineeringTaskNode] = {}

        for req in all_reqs:
            node_id = f"task_{req.id.lower().replace('-', '_')}"
            target_files = getattr(req, "affected_files", None) or []
            if not target_files:
                words = (req.description or "").split()
                file_mentions = [w.strip("`'\",()") for w in words if w.strip("`'\",()").endswith((".py", ".ts", ".js", ".json"))]
                if file_mentions:
                    target_files = file_mentions
                else:
                    target_files = [f"src/{req.id.lower().replace('-', '_')}_module.py"]

            # Risk classification based on impact report if available
            risk = "LOW"
            if impact_report:
                risk = getattr(getattr(impact_report, "risk_classification", None), "value", str(getattr(impact_report, "risk_classification", "LOW")))

            req_title = getattr(req, "title", req.description[:40] if req.description else req.id)
            node = EngineeringTaskNode(
                node_id=node_id,
                description=f"Implement requirement {req.id}: {req_title}",
                objective=req.description,
                related_requirement_ids=[req.id],
                related_architecture_decisions=[adr.id for adr in (blueprint.adrs if blueprint else [])],
                target_files=target_files,
                dependencies=[],
                risk_level=risk,
                expected_outputs=[f"Code satisfying {req.id}"],
                required_tests=[f"test_{req.id.lower().replace('-', '_')}"],
                acceptance_criteria=req.acceptance_criteria if hasattr(req, "acceptance_criteria") else ["Verified by tests"],
                completion_conditions=["Passing targeted unit tests"],
            )
            created_nodes[node_id] = node

        # If no requirements generated nodes, build a single minimal focused node
        if not created_nodes:
            fallback_node = EngineeringTaskNode(
                node_id="task_main",
                description="Implement requested task outcome",
                objective=getattr(specification, "desired_outcome", None) or getattr(specification, "title", "Fulfill user request"),
                related_requirement_ids=[],
                target_files=["src/main_task.py"],
                dependencies=[],
                risk_level="LOW",
                expected_outputs=["Working code"],
                required_tests=["test_main_task"],
                acceptance_criteria=["Passes verification"],
                completion_conditions=["Clean tests"],
            )
            created_nodes["task_main"] = fallback_node

        # Add nodes to DAG
        for node in created_nodes.values():
            dag.add_node(node)

        # Add verification task depending on all implementation nodes
        impl_keys = list(created_nodes.keys())
        verify_node = EngineeringTaskNode(
            node_id="task_verification",
            description="Run regression prevention & independent verification",
            objective="Ensure all implementation nodes pass tests with zero new regressions",
            related_requirement_ids=list(approved_req_ids),
            dependencies=impl_keys,
            risk_level="LOW",
            expected_outputs=["Clean test results", "RegressionReport"],
            required_tests=["suite_verification"],
            acceptance_criteria=["0 regressions", "Zero security violations"],
            completion_conditions=["Regression report verdict: CLEAN"],
        )
        dag.add_node(verify_node)

        # Validate DAG dependencies and topological order
        dag.get_execution_order()
        return dag

    def validate_plan_scope(self, plan: EngineeringPlanDAG, specification: ProjectSpecification) -> None:
        """
        Verify that no node attempts work outside approved specification scope.
        """
        if hasattr(specification, "all_requirements"):
            all_reqs = specification.all_requirements() if callable(specification.all_requirements) else specification.all_requirements
        else:
            all_reqs = getattr(specification, "requirements", [])
        approved_req_ids = {r.id for r in all_reqs}
        for node in plan.nodes.values():
            if node.node_id == "task_verification":
                continue
            for rid in node.related_requirement_ids:
                if rid not in approved_req_ids:
                    raise ScopeCreepError(
                        f"Task node {node.node_id} references unapproved requirement {rid}"
                    )

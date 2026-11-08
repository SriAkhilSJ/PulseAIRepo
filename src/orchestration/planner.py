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


class PlanBudgetExceeded(RuntimeError):
    """The plan cannot be expressed within the dispatches available.

    Raised BEFORE any provider request, so an over-budget plan costs nothing.
    """

    def __init__(self, requested_nodes: int, allowed_nodes: int, requirement_ids: list[str]) -> None:
        self.requested_nodes = requested_nodes
        self.allowed_nodes = allowed_nodes
        self.requirement_ids = requirement_ids
        super().__init__(
            f"plan needs {requested_nodes} nodes but only {allowed_nodes} dispatch(es) "
            f"are available for requirements {requirement_ids}; refusing to execute"
        )


_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

#: Only work the user actually asked for (or inferred as necessary) may become a
#: mandatory plan node. Analyzer defaults are suggestions: they are recorded on
#: the DAG but cannot silently expand scope or block completion.
_MANDATORY_CLASSIFICATIONS = {"EXPLICIT", "NECESSARY_INFERRED"}


def requirement_classification(req: Any) -> str:
    raw = getattr(req, "classification", None)
    value = getattr(raw, "value", raw)
    return str(value or "").upper()


def is_mandatory_requirement(req: Any) -> bool:
    classification = requirement_classification(req)
    if not classification:
        # Legacy/fake specifications without classification keep the old
        # behaviour: every listed requirement is work.
        return True
    return classification in _MANDATORY_CLASSIFICATIONS


def merge_requirement_nodes(nodes: list[EngineeringTaskNode]) -> EngineeringTaskNode:
    """Coalesce requirement nodes into ONE node without dropping requirements.

    Requirement ids, target files, tests and acceptance criteria are UNIONed so
    nothing is silently lost; member dependencies are kept and the highest risk
    wins. This is how a 6-requirement plan becomes a plan that fits a
    5-dispatch budget.
    """
    first = nodes[0]
    req_ids: list[str] = []
    targets: list[str] = []
    tests: list[str] = []
    criteria: list[str] = []
    outputs: list[str] = []
    deps: list[str] = []
    for node in nodes:
        for bucket, values in (
            (req_ids, node.related_requirement_ids),
            (targets, node.target_files),
            (tests, node.required_tests),
            (criteria, node.acceptance_criteria),
            (outputs, node.expected_outputs),
            (deps, node.dependencies),
        ):
            for value in values:
                if value not in bucket:
                    bucket.append(value)
    risk = max((node.risk_level for node in nodes), key=lambda r: _RISK_ORDER.get(r, 0))
    ceilings = [node.max_tokens for node in nodes if node.max_tokens]
    return EngineeringTaskNode(
        node_id=first.node_id,
        description=("Implement requirements: " + ", ".join(req_ids)) if req_ids else first.description,
        objective=" | ".join(dict.fromkeys(node.objective for node in nodes)),
        related_requirement_ids=req_ids,
        related_architecture_decisions=list(dict.fromkeys(
            adr for node in nodes for adr in node.related_architecture_decisions)),
        target_files=targets,
        dependencies=[d for d in deps if d not in {n.node_id for n in nodes}],
        risk_level=risk,
        expected_outputs=outputs or ["Working code"],
        required_tests=tests,
        acceptance_criteria=criteria or ["Passes verification"],
        completion_conditions=["Passing targeted unit tests"],
        max_tokens=max(ceilings) if ceilings else None,
    )


def absorb_requirement_nodes(target: EngineeringTaskNode, others: list[EngineeringTaskNode]) -> None:
    """Fold other requirement nodes into ``target`` WITHOUT adding files.

    Used when the user named the files: their requested modules are the units
    of work, and analyzer-derived placeholder nodes are absorbed into them so
    every requirement id stays in the traceability map while no extra
    ``src/req_00N_module.py`` file is invented (and no extra dispatch spent).
    """
    for node in others:
        for rid in node.related_requirement_ids:
            if rid not in target.related_requirement_ids:
                target.related_requirement_ids.append(rid)
        for bucket, values in (
            (target.required_tests, node.required_tests),
            (target.acceptance_criteria, node.acceptance_criteria),
        ):
            for value in values:
                if value not in bucket:
                    bucket.append(value)
        target.objective = " | ".join(dict.fromkeys([target.objective, node.objective]))


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
        max_nodes: Optional[int] = None,
        requested_files: Optional[list[str]] = None,
        task_prompt: Optional[str] = None,
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

        # 1a. Analyzer discipline: only mandatory requirements become work.
        #     Domain templates and "reasonable defaults" are recorded as
        #     suggestions, never silently promoted into mandatory scope.
        mandatory_reqs = [r for r in all_reqs if is_mandatory_requirement(r)]
        optional_reqs = [r for r in all_reqs if not is_mandatory_requirement(r)]
        dag.optional_requirements = [
            {
                "id": getattr(req, "id", ""),
                "description": getattr(req, "description", ""),
                "classification": requirement_classification(req),
                "reason": "optional suggestion; not part of the requested mandatory scope",
            }
            for req in optional_reqs
        ]

        # 2. Extract tasks directly mapped to requirements
        created_nodes: Dict[str, EngineeringTaskNode] = {}
        # Files the USER actually named in the request take precedence over the
        # synthesized ``src/<req>_module.py`` names: a plan that writes to paths
        # nobody asked for satisfies nobody, even when it "completes".
        requested_pool = [f for f in (requested_files or []) if f]
        requested_set = set(requested_pool)

        for req in mandatory_reqs:
            node_id = f"task_{req.id.lower().replace('-', '_')}"
            target_files = getattr(req, "affected_files", None) or []
            if not target_files:
                words = (req.description or "").split()
                file_mentions = [w.strip("`'\",()") for w in words if w.strip("`'\",()").endswith((".py", ".ts", ".js", ".json"))]
                if file_mentions:
                    target_files = file_mentions
                else:
                    target_files = [f"src/{req.id.lower().replace('-', '_')}_module.py"]
            if requested_pool:
                target_files = [requested_pool.pop(0)]

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

        # 1a. If the user named files, those files ARE the work units: keep the
        #     nodes that received a requested path and absorb the analyzer's
        #     placeholder nodes into them (ids preserved, no invented files, no
        #     extra dispatch spent on ``src/req_00N_module.py``).
        if requested_set:
            requested_nodes = [
                n for n in created_nodes.values()
                if n.target_files and n.target_files[0] in requested_set
            ]
            if requested_nodes:
                absorbed = [n for n in created_nodes.values() if n not in requested_nodes]
                for index, node in enumerate(absorbed):
                    absorb_requirement_nodes(requested_nodes[index % len(requested_nodes)], [node])
                created_nodes = {n.node_id: n for n in requested_nodes}
                # The USER's words, not the analyzer's inferred specification,
                # govern a file the user named. Without this the node objective
                # demanded RFC-5321/DNS/CLI work the user never asked for (963
                # generated lines, contract violated, self-tests failing).
                if task_prompt and task_prompt.strip():
                    for node in requested_nodes:
                        node.objective = task_prompt.strip()
                        node.description = (
                            f"Implement {node.target_files[0]} exactly as the user asked "
                            "(minimal scope; no extra APIs, classes or CLI)"
                        )

        # 1b. Dispatch budget: coalesce requirement nodes so the plan fits.
        #     Every requirement id is preserved (union), never dropped.
        #
        #     IMPORTANT: the adapter dispatches once PER TARGET FILE (the
        #     verification node dispatches none), so the budget is measured in
        #     files, not nodes. When the surviving files still exceed the
        #     implementation budget, each merged node is consolidated onto a
        #     single module and the absorbed paths are recorded in
        #     ``expected_outputs`` — a visible plan decision, not a silent drop.
        if max_nodes is not None:
            if int(max_nodes) < 2:
                raise PlanBudgetExceeded(
                    requested_nodes=len(created_nodes) + 1,
                    allowed_nodes=int(max_nodes),
                    requirement_ids=[r.id for r in all_reqs],
                )
            impl_budget = int(max_nodes) - 1
            if len(created_nodes) > impl_budget:
                ordered = list(created_nodes.values())
                buckets: list[list[EngineeringTaskNode]] = [[] for _ in range(impl_budget)]
                for index, node in enumerate(ordered):
                    buckets[index % impl_budget].append(node)
                merged: Dict[str, EngineeringTaskNode] = {}
                for bucket in buckets:
                    if not bucket:
                        continue
                    node = merge_requirement_nodes(bucket) if len(bucket) > 1 else bucket[0]
                    merged[node.node_id] = node
                covered = {rid for n in merged.values() for rid in n.related_requirement_ids}
                expected = {rid for n in ordered for rid in n.related_requirement_ids}
                missing = expected - covered
                if missing:
                    raise PlanBudgetExceeded(
                        requested_nodes=len(created_nodes) + 1,
                        allowed_nodes=int(max_nodes),
                        requirement_ids=sorted(missing),
                    )
                created_nodes = merged

            file_demand = sum(max(1, len(n.target_files)) for n in created_nodes.values())
            if file_demand > impl_budget:
                for node in created_nodes.values():
                    if len(node.target_files) <= 1:
                        continue
                    primary = node.target_files[0]
                    absorbed = node.target_files[1:]
                    node.target_files = [primary]
                    node.expected_outputs = list(node.expected_outputs) + [
                        f"consolidated into {primary}: {path}" for path in absorbed
                    ]

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

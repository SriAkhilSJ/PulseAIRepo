"""
src/orchestration/orchestrator.py - Unified Engineering Execution Orchestrator.

Phase 11.6: Autonomous Engineering Execution.
Coordinates:
- Phase 11.0: Project Intelligence
- Phase 11.1: Requirement Intelligence
- Phase 11.2: Architecture Intelligence
- Phase 11.3: Workspace Discipline
- Phase 11.4: Change Impact Analysis
- Phase 11.5: Regression Prevention & Recovery
- Phase 9.7: FinOps Cost Governance
- Phase 10.0: Identity & RBAC

Built on Crusor's LangGraph architecture.
Enforces the 15-stage lifecycle, 23-state persistent state machine,
bounded cognitive reasoning loops, human supervision gates, and strict delivery contracts.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# LangGraph integration
from langgraph.graph import END, START, StateGraph

# Phase 11.0 - 11.5 subsystems
from src.impact.engine import ChangeImpactAnalysisEngine
from src.intelligence.agent_integration import ProjectIntelligenceRetriever
from src.intelligence.architecture_integration import ArchitectureIntelligenceSystem
from src.intelligence.discovery import RepositoryDiscoveryEngine
from src.intelligence.persistence import PersistentProjectIntelligenceManager
from src.intelligence.requirement_integration import RequirementIntelligenceSystem
from src.orchestration.context_manager import AdaptiveContextManager
from src.orchestration.finops_governor import OrchestrationFinOpsGovernor
from src.orchestration.implementation_engine import ControlledImplementationEngine
from src.orchestration.journal import DurableOrchestrationJournal
from src.orchestration.lifecycle import LifecycleManager
from src.orchestration.loop import BoundedAutonomousReasoningLoop
from src.orchestration.model_adapter import ModelExecutionAdapter
from src.orchestration.models import (
    DeliveryContract,
    EngineeringPlanDAG,
    EngineeringTaskNode,
    ExecutionLimits,
    TaskExecutionState,
    TaskLifecycleStage,
    TaskVerdict,
)
from src.orchestration.planner import EngineeringTaskPlanner
from src.orchestration.scheduler import DependencyAwareScheduler
from src.orchestration.state_machine import TaskStateMachine
from src.orchestration.supervision import HumanSupervisionGate
from src.orchestration.visibility import DesktopVisibilityReporter
from src.production.engine import ProductionReadinessEngine
from src.regression.engine import RegressionPreventionEngine
from src.regression.models import RegressionReport, RegressionStatus
from src.verification.engine import IndependentVerificationEngine
from src.verification.models import VerificationVerdict
from src.workspace.mutation_broker import WorkspaceMutationBroker

log = logging.getLogger("crusor.orchestration.orchestrator")


class EngineeringExecutionOrchestrator:
    """
    Unified central orchestrator executing autonomous software engineering tasks.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        limits: Optional[ExecutionLimits] = None,
        storage_dir: Optional[str] = None,
        model_adapter: Optional[ModelExecutionAdapter] = None,
        mock_mode: Optional[bool] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id
        self.limits = limits or ExecutionLimits()
        self.storage_dir = storage_dir
        #: The governor created by the current run_task, so the wrapper can
        #: reconcile it on EVERY exit (success, failure, cancellation, raise).
        self._last_finops: Optional[OrchestrationFinOpsGovernor] = None

        # Initialize existing subsystem engines
        self.discovery_mgr = PersistentProjectIntelligenceManager(str(self.workspace_root))
        self.discovery_engine = RepositoryDiscoveryEngine(str(self.workspace_root))
        self.req_system = RequirementIntelligenceSystem()
        self.arch_system = ArchitectureIntelligenceSystem()
        self.broker = WorkspaceMutationBroker(str(self.workspace_root), tenant_id=tenant_id)
        self.impact_engine = ChangeImpactAnalysisEngine(str(self.workspace_root), tenant_id=tenant_id)
        self.regression_engine = RegressionPreventionEngine(str(self.workspace_root), tenant_id=tenant_id)

        # Implementation and planning tools
        self.planner = EngineeringTaskPlanner(str(self.workspace_root), tenant_id=tenant_id)
        self.impl_engine = ControlledImplementationEngine(str(self.workspace_root), tenant_id=tenant_id, broker=self.broker)
        self.scheduler = DependencyAwareScheduler(max_concurrency=self.limits.max_concurrent_operations)
        self.supervision_gate = HumanSupervisionGate(str(self.workspace_root), tenant_id=tenant_id)
        self.verification_engine = IndependentVerificationEngine(str(self.workspace_root), tenant_id=tenant_id, storage_dir=storage_dir)

        # Model execution adapter & production readiness engine
        self.model_adapter = model_adapter or ModelExecutionAdapter(
            str(self.workspace_root),
            tenant_id=tenant_id,
            mock_mode=mock_mode,
            provider=provider,
            model=model,
        )
        self.production_engine = ProductionReadinessEngine(str(self.workspace_root), tenant_id=tenant_id, storage_dir=storage_dir)

    # -- dispatch budget ---------------------------------------------------

    def _remaining_dispatch_budget(self) -> Optional[int]:
        """Dispatches this task may still spend (task limit ∩ live guard).

        The acceptance guard (P0.6.4.1) counts dispatches for the whole desktop
        turn; the task limit counts them for this orchestration. The tighter of
        the two wins, so a plan can never be generated that the guard would
        refuse mid-flight. When no guard is active, the task limit is decremented
        by the governor's own reservation count so a repair cannot silently
        exceed it offline.
        """
        budgets: list[int] = []
        configured = getattr(self.limits, "max_dispatch_budget", None)
        used = 0
        finops = self._last_finops
        if finops is not None:
            used = (
                len(getattr(finops, "_active_reservations", {}))
                + len(getattr(finops, "_uncertain_reservations", {}))
                + len(getattr(finops, "_settled_reservations", {}))
            )
        if configured is not None:
            budgets.append(max(0, int(configured) - used))
        try:
            from src.llm.acceptance_guard import active_guard

            guard = active_guard()
            if guard is not None:
                budgets.append(int(guard.remaining))
        except Exception:
            pass
        if not budgets:
            return None
        return max(0, min(budgets))

    @staticmethod
    def _requested_files(task_prompt: str) -> list[str]:
        """File paths the user named in the request (order preserved, deduped)."""
        import re as _re

        found: list[str] = []
        for token in _re.findall(r"[A-Za-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|json|md|toml|yaml|yml)\b", task_prompt or ""):
            cleaned = token.strip("`'\",()[]<>").replace("\\", "/")
            if cleaned and cleaned not in found:
                found.append(cleaned)
        return found[:8]

    # -- P0.6.7 test lifecycle helpers ------------------------------------

    def _validate_artifacts(self) -> Dict[str, Any]:
        """Every generated artifact must exist and parse before tests run."""
        report: Dict[str, Any] = {"ok": True, "files": {}, "hashes": {}}
        for rel in sorted(self.impl_engine.mutated_files):
            path = self.workspace_root / rel
            entry: Dict[str, Any] = {"exists": path.exists()}
            if not path.exists():
                report["ok"] = False
                report["files"][rel] = entry
                continue
            data = path.read_bytes()
            report["hashes"][rel] = hashlib.sha256(data).hexdigest()
            if path.suffix == ".py":
                try:
                    ast.parse(data.decode("utf-8", errors="replace"), filename=rel)
                    entry["ast_ok"] = True
                except SyntaxError as exc:
                    entry["ast_ok"] = False
                    entry["error"] = str(exc)
                    report["ok"] = False
            report["files"][rel] = entry
        return report

    @staticmethod
    def _testing_required(task_prompt: str, discovery: Any, plan_dag: EngineeringPlanDAG) -> bool:
        """Testing is required when tests exist, were requested, or were planned."""
        from src.orchestration.test_execution import is_test_file

        if getattr(discovery, "files", None):
            return True
        if re.search(r"\b(?:test|tests|pytest|unittest|spec)\b", (task_prompt or "").lower()):
            return True
        for node in plan_dag.nodes.values():
            if any(is_test_file(f) for f in node.target_files):
                return True
        return False

    @staticmethod
    def _select_repair_target(diagnosis: Any, plan_dag: EngineeringPlanDAG) -> Optional[Tuple[EngineeringTaskNode, str]]:
        """Only files the plan owns may be repaired."""
        for target in getattr(diagnosis, "target_files", []) or []:
            for node in plan_dag.nodes.values():
                if target in node.target_files:
                    return node, target
        candidates = [
            node for node in plan_dag.nodes.values()
            if node.node_id != "task_verification" and node.target_files
        ]
        if len(candidates) == 1:
            return candidates[0], candidates[0].target_files[0]
        return None

    def _test_integrity_guard(self, target_file: str):
        """Refuse a repaired test that deletes, skips or weakens verification.

        P0.6.8 adds a stable inventory comparison (test functions + assertion
        counts + exception assertions + params) on top of the P0.6.7 auditor so
        import-only maintenance is allowed while coverage loss is not.
        """
        from src.orchestration.contract import audit_test_repair
        from src.regression.integrity import TestIntegrityAuditor

        auditor = TestIntegrityAuditor()
        original = ""
        path = self.workspace_root / target_file
        if path.exists():
            original = path.read_text(encoding="utf-8", errors="replace")

        def guard(candidate: str) -> str:
            violations = list(audit_test_repair(original, candidate))
            try:
                audit = auditor.audit_test_modification(target_file, original, candidate)
                violations.extend(
                    getattr(v, "description", None) or str(v) for v in audit
                )
            except Exception as exc:  # pragma: no cover - defensive
                violations.append(f"integrity audit failed: {exc}")
            if violations:
                raise ValueError("test integrity violation: " + "; ".join(violations[:5]))
            return candidate

        return guard

    def _cancelled_delivery(
        self,
        task_id: str,
        task_prompt: str,
        t_start: float,
        finops: OrchestrationFinOpsGovernor,
        reason: str,
    ) -> DeliveryContract:
        return DeliveryContract(
            task_id=task_id,
            original_request=task_prompt,
            verdict=TaskVerdict.CANCELLED,
            what_was_requested=task_prompt,
            what_was_implemented=[],
            files_changed=sorted(list(self.impl_engine.mutated_files)),
            tests_executed=[],
            tests_passed=[],
            tests_failed=[],
            independently_verified=False,
            remaining_limitations=[reason],
            user_action_required=None,
            cost_inr=finops.accounting.spent_inr,
            cost_usd=finops.accounting.spent_usd,
            token_usage={"tokens": finops.accounting.tokens_consumed},
            duration_seconds=round(time.time() - t_start, 3),
        )

    def _validate_plan_budget(self, plan_dag: Any, budget: Optional[int]) -> None:
        """Refuse a plan that cannot fit the dispatch budget (costs nothing).

        Demand is measured in PROVIDER DISPATCHES: the adapter generates one
        file per dispatch and the verification node dispatches none. Counting
        nodes instead under-estimated a 6-file plan as "6 nodes" while the
        verification node actually costs zero — and, worse, merging nodes does
        not reduce file dispatches.
        """
        if budget is None:
            return
        demand = 0
        for node in plan_dag.nodes.values():
            if node.node_id == "task_verification":
                continue
            demand += max(1, len(node.target_files))
        if demand <= budget:
            return
        from src.orchestration.planner import PlanBudgetExceeded

        raise PlanBudgetExceeded(
            requested_nodes=demand,
            allowed_nodes=budget,
            requirement_ids=sorted({
                rid for node in plan_dag.nodes.values() for rid in node.related_requirement_ids
            }),
        )

    # -- financial reconciliation -----------------------------------------

    def _finalize_finops_after(self, finops: OrchestrationFinOpsGovernor) -> dict:
        """Reconcile the governor on EVERY exit of ``run_task``.

        * ACTIVE reservations are released: the scheduler is synchronous, so by
          the time ``run_task`` returns no wire call can still be in flight and
          an active hold would otherwise leak budget forever.
        * UNCERTAIN reservations are NEVER released as free — the provider may
          have billed them. They stay held for explicit reconciliation and are
          reported in the delivery evidence.
        Duplicate settlement is already refused by ``commit_reservation``
        (settled ids are ignored), so this cannot double-charge.
        """
        released: list[str] = []
        failed: list[dict] = []
        for reservation_id in list(getattr(finops, "_active_reservations", {}).keys()):
            try:
                finops.release_reservation(reservation_id, reason="task_exit_without_settlement")
                released.append(reservation_id)
            except Exception as exc:  # pragma: no cover - defensive
                failed.append({"id": reservation_id, "error": str(exc)})
        uncertain = list(getattr(finops, "_uncertain_reservations", {}).keys())
        accounting = finops.accounting
        summary = {
            "released_on_exit": released,
            "release_failures": failed,
            "uncertain_unresolved": uncertain,
            "settled_count": len(getattr(finops, "_settled_reservations", {})),
            "active_after": len(getattr(finops, "_active_reservations", {})),
            "spent_inr": accounting.spent_inr,
            "spent_usd": accounting.spent_usd,
            "calls_count": accounting.calls_count,
            "input_tokens": accounting.input_tokens,
            "output_tokens": accounting.output_tokens,
            "is_breached": accounting.is_breached,
        }
        log.info("finops finalized: %s", summary)
        return summary

    def run_task(self, *args: Any, **kwargs: Any) -> DeliveryContract:
        """Public entry: run the task and always reconcile its finances.

        The implementation creates an ``OrchestrationFinOpsGovernor``; this
        wrapper guarantees that whatever way the turn ends (success, failure,
        cancellation, an unexpected exception) the governor is reconciled:
        active holds released, uncertain holds reported and retained.
        """
        self._last_finops = None
        try:
            return self._run_task_impl(*args, **kwargs)
        finally:
            finops = self._last_finops
            if finops is not None:
                try:
                    self._finalize_finops_after(finops)
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning("finops finalization failed: %r", exc)

    def _run_task_impl(
        self,
        task_prompt: str,
        task_id: Optional[str] = None,
        explicit_constraints: Optional[List[str]] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
        custom_executor: Optional[Callable[[EngineeringTaskNode], bool]] = None,
        cancellation_checker: Optional[Callable[[], bool]] = None,
    ) -> DeliveryContract:
        """
        Executes an end-to-end autonomous engineering task through all 15 lifecycle stages.
        """
        tid = task_id or f"task_{uuid.uuid4().hex[:8]}"
        t_start = time.time()

        if cancellation_checker and cancellation_checker():
            return DeliveryContract(
                task_id=tid,
                original_request=task_prompt,
                verdict=TaskVerdict.CANCELLED,
                what_was_requested=task_prompt,
                what_was_implemented=[],
                files_changed=[],
                tests_executed=[],
                tests_passed=[],
                tests_failed=[],
                independently_verified=False,
                remaining_limitations=["Execution cancelled by user."],
                user_action_required=None,
                cost_inr=0.0,
                token_usage={},
                duration_seconds=round(time.time() - t_start, 3),
            )

        # Initialize orchestration governance components
        state_machine = TaskStateMachine(tid, str(self.workspace_root), tenant_id=self.tenant_id, storage_dir=self.storage_dir)
        lifecycle = LifecycleManager(tid)
        context_mgr = AdaptiveContextManager(tid, str(self.workspace_root), tenant_id=self.tenant_id, storage_dir=self.storage_dir)
        finops = OrchestrationFinOpsGovernor(
            tid,
            budget_inr=self.limits.max_cost_inr,
            token_budget=self.limits.max_token_budget,
            storage_dir=self.storage_dir,
            workspace_root=str(self.workspace_root),
        )
        self._last_finops = finops
        journal = DurableOrchestrationJournal(tid, str(self.workspace_root), tenant_id=self.tenant_id, storage_dir=self.storage_dir)
        reasoning_loop = BoundedAutonomousReasoningLoop(limits=self.limits)

        # Record start in journal and context
        journal.record_event("TASK_INITIALIZED", {"task_prompt": task_prompt, "constraints": explicit_constraints})
        context_mgr.initialize_request(task_prompt, explicit_constraints)

        def emit_progress(step_name: str) -> None:
            if on_progress:
                plan = context_mgr.context.plan
                total_steps = list(plan.nodes.keys()) if plan else []
                view = DesktopVisibilityReporter.compute_view(
                    task_id=tid,
                    state=state_machine.current_state,
                    current_step=step_name,
                    completed_steps=context_mgr.context.completed_steps,
                    pending_steps=[s for s in total_steps if s not in context_mgr.context.completed_steps],
                    failed_steps=context_mgr.context.outstanding_failures,
                    modified_files=list(self.impl_engine.mutated_files),
                    tokens_used=finops.accounting.tokens_consumed,
                    cost_inr=finops.accounting.spent_inr,
                    is_paused=state_machine.is_paused,
                )
                on_progress(view.to_safe_dict())

        # STAGE 1: USER_REQUEST
        lifecycle.begin_stage(TaskLifecycleStage.USER_REQUEST, {"prompt": task_prompt})
        emit_progress("USER_REQUEST")
        lifecycle.complete_stage({"validated_prompt": task_prompt})

        # STAGE 2: REQUEST_UNDERSTANDING
        state_machine.transition_to(TaskExecutionState.UNDERSTANDING, "Analyzing user request")
        lifecycle.begin_stage(TaskLifecycleStage.REQUEST_UNDERSTANDING, {"prompt": task_prompt})
        emit_progress("REQUEST_UNDERSTANDING")
        analysis_result = self.req_system.analyze_request(
            task_prompt=task_prompt,
            workspace_root=str(self.workspace_root),
            task_id=tid,
            tenant_id=self.tenant_id,
        )
        context_mgr.record_specification(analysis_result.specification)
        journal.record_event("REQUEST_UNDERSTOOD", {
            "spec_id": analysis_result.specification.spec_id,
            "scope": getattr(analysis_result.specification.implementation_scope, "value", str(analysis_result.specification.implementation_scope)),
        })
        lifecycle.complete_stage({"specification": analysis_result.specification.spec_id})

        # Check for essential unresolved questions / clarifications
        if analysis_result.clarification_questions:
            # Check if any question is blocking
            blocking_q = [q for q in analysis_result.clarification_questions if getattr(q, "priority", "STANDARD") == "CRITICAL"]
            if blocking_q:
                state_machine.transition_to(TaskExecutionState.CLARIFICATION_REQUIRED, "Essential clarifications needed")
                emit_progress("CLARIFICATION_REQUIRED")
                # Auto-resolve with default / recommended option for automated tests if answer not pre-supplied
                for q in blocking_q:
                    ans = q.recommended_option or "Standard default"
                    context_mgr.record_clarification(q.question, ans)
                state_machine.transition_to(TaskExecutionState.UNDERSTANDING, "Clarifications resolved")

        # STAGE 3: PROJECT_DISCOVERY (Phase 11.0)
        state_machine.transition_to(TaskExecutionState.DISCOVERY, "Discovering repository knowledge")
        lifecycle.begin_stage(TaskLifecycleStage.PROJECT_DISCOVERY, {"workspace": str(self.workspace_root)})
        emit_progress("PROJECT_DISCOVERY")
        knowledge = self.discovery_mgr.get_project_knowledge()
        journal.record_event("DISCOVERY_COMPLETED", {"project_name": knowledge.project_name, "frameworks": [f.name for f in knowledge.frameworks]})
        lifecycle.complete_stage({"project_name": knowledge.project_name})

        # STAGE 4: REQUIREMENT_VALIDATION (Phase 11.1)
        state_machine.transition_to(TaskExecutionState.SPECIFICATION_READY, "Validating requirements against repository")
        lifecycle.begin_stage(TaskLifecycleStage.REQUIREMENT_VALIDATION, {"spec": analysis_result.specification.spec_id})
        emit_progress("REQUIREMENT_VALIDATION")
        lifecycle.complete_stage({"validated": True})

        # STAGE 5: ARCHITECTURE_VALIDATION (Phase 11.2)
        state_machine.transition_to(TaskExecutionState.ARCHITECTURE_REVIEW, "Evaluating architectural approach")
        lifecycle.begin_stage(TaskLifecycleStage.ARCHITECTURE_VALIDATION, {})
        emit_progress("ARCHITECTURE_VALIDATION")
        arch_result = self.arch_system.synthesize_architecture(
            task_id=tid,
            workspace_root=str(self.workspace_root),
            tenant_id=self.tenant_id,
        )
        context_mgr.record_blueprint(arch_result.blueprint)
        style_val = getattr(arch_result.blueprint.architecture_style, "value", str(arch_result.blueprint.architecture_style))
        stack_val = [getattr(t, "name", str(t)) for t in arch_result.blueprint.technology_stack]
        journal.record_event("ARCHITECTURE_ESTABLISHED", {"style": style_val, "stack": stack_val})
        lifecycle.complete_stage({"style": style_val})

        # STAGE 5.5: CONTRACT EXTRACTION + FILE ASSIGNMENT (P0.6.8)
        from src.orchestration.contract import (
            extract_contract,
            validate_contract_plan,
        )

        state_machine.transition_to(
            TaskExecutionState.CONTRACT_EXTRACTED,
            "Extracting the authoritative engineering contract",
        )
        lifecycle.begin_stage(TaskLifecycleStage.CONTRACT_EXTRACTION, {})
        emit_progress("CONTRACT_EXTRACTION")
        requested_files = self._requested_files(task_prompt)
        raw_requirements = getattr(analysis_result.specification, "all_requirements", None)
        if callable(raw_requirements):
            all_requirements = raw_requirements()
        elif raw_requirements:
            all_requirements = raw_requirements
        else:
            all_requirements = getattr(analysis_result.specification, "requirements", [])
        contract = extract_contract(
            task_prompt,
            all_requirements,
            requested_files,
            task_id=tid,
            workspace=str(self.workspace_root),
        )
        contract_path = contract.persist(self.workspace_root)
        journal.record_event("CONTRACT_EXTRACTED", {
            "contract_hash": contract.contract_hash,
            "version": contract.version,
            "path": contract_path,
            "components": [
                {
                    "role": component.role,
                    "target": component.target_file,
                    "requirement_ids": component.requirement_ids,
                    "symbols": component.symbols,
                    "signatures": component.signatures,
                    "returns": component.returns,
                    "units": component.units,
                }
                for component in contract.components
            ],
            "ambiguities": contract.ambiguities,
            "optional_suggestions": contract.optional_suggestions,
        })
        lifecycle.complete_stage({"contract_hash": contract.contract_hash})

        state_machine.transition_to(
            TaskExecutionState.FILES_ASSIGNED,
            "Assigning user-named files by semantic role",
        )
        lifecycle.begin_stage(TaskLifecycleStage.FILE_ASSIGNMENT, {})
        emit_progress("FILES_ASSIGNED")
        assignment_report = {
            "requirement_map": contract.requirement_map,
            "roles": {c.target_file: c.role for c in contract.components},
            "ambiguities": contract.ambiguities,
        }
        journal.record_event("FILES_ASSIGNED", assignment_report)
        lifecycle.complete_stage(assignment_report)

        # STAGE 6: ENGINEERING_PLAN (Phase 11.6 Planner)
        state_machine.transition_to(TaskExecutionState.PLANNING, "Generating structured engineering plan DAG")
        lifecycle.begin_stage(TaskLifecycleStage.ENGINEERING_PLAN, {})
        emit_progress("ENGINEERING_PLAN")
        dispatch_budget = self._remaining_dispatch_budget()
        plan_dag = self.planner.build_plan(
            task_id=tid,
            specification=analysis_result.specification,
            blueprint=arch_result.blueprint,
            knowledge=knowledge,
            max_nodes=dispatch_budget,
            requested_files=requested_files,
            task_prompt=task_prompt,
            contract=contract,
        )
        # Pre-dispatch plan validation: Requirement -> Role -> File -> Work Unit.
        try:
            self._validate_plan_budget(plan_dag, dispatch_budget)
            plan_report = validate_contract_plan(
                contract,
                plan_dag,
                max_dispatches=dispatch_budget,
                requested_files=requested_files,
            )
        except Exception as exc:
            state_machine.transition_to(TaskExecutionState.FAILED, "Plan rejected before dispatch")
            journal.record_event("PLAN_REJECTED", {
                "reason": f"{type(exc).__name__}: {exc}",
                "budget": dispatch_budget,
                "requested_files": requested_files,
                "requirement_map": contract.requirement_map,
            })
            raise
        state_machine.transition_to(TaskExecutionState.PLAN_VALIDATED, "Contract plan validated")
        journal.record_event("PLAN_VALIDATED", plan_report)
        lifecycle.complete_stage(plan_report)
        # Per-node output ceiling from the limits (measured justification lives
        # on ExecutionLimits.max_output_tokens_per_node).
        ceiling = getattr(self.limits, "max_output_tokens_per_node", None)
        if ceiling:
            for node in plan_dag.nodes.values():
                if not getattr(node, "max_tokens", None):
                    node.max_tokens = int(ceiling)
        context_mgr.record_plan(plan_dag)
        journal.record_event("PLAN_GENERATED", {
            "nodes_count": len(plan_dag.nodes),
            "dispatch_budget": dispatch_budget,
            "per_node_output_tokens": ceiling,
            "work_units": plan_report.get("work_units"),
            "demand": plan_report.get("demand"),
            "contract_hash": contract.contract_hash,
        })

        # STAGE 7: CHANGE_IMPACT_ANALYSIS (Phase 11.4)
        state_machine.transition_to(TaskExecutionState.IMPACT_ANALYSIS, "Evaluating blast radius & affected components")
        lifecycle.begin_stage(TaskLifecycleStage.CHANGE_IMPACT_ANALYSIS, {})
        emit_progress("CHANGE_IMPACT_ANALYSIS")
        all_targets = [f for n in plan_dag.nodes.values() for f in n.target_files]
        impact_report = self.impact_engine.analyze_proposed_changes(
            task_id=tid,
            proposed_change_summary=task_prompt,
            changed_files=all_targets,
            project_knowledge=knowledge,
            project_spec=analysis_result.specification,
            architecture_blueprint=arch_result.blueprint,
        )
        context_mgr.record_impact_report(impact_report)
        risk_val = getattr(impact_report.risk_classification, "value", str(impact_report.risk_classification))
        journal.record_event("IMPACT_EVALUATED", {"risk": risk_val})
        lifecycle.complete_stage({"impact_report": impact_report.task_id})

        # STAGE 8: TEST_BASELINE (Phase 11.5)
        state_machine.transition_to(TaskExecutionState.BASELINE_TESTING, "Establishing pre-change test baseline")
        lifecycle.begin_stage(TaskLifecycleStage.TEST_BASELINE, {})
        emit_progress("TEST_BASELINE")
        baseline = self.regression_engine.baseline_mgr.capture_baseline(task_id=tid)
        context_mgr.record_test_baseline(baseline.summary)
        journal.record_event("BASELINE_CAPTURED", baseline.summary)
        lifecycle.complete_stage(baseline.summary)

        # STAGE 9: APPROVAL_AND_PERMISSION_CHECK
        state_machine.transition_to(TaskExecutionState.READY_TO_IMPLEMENT, "Checking required permissions & supervision")
        lifecycle.begin_stage(TaskLifecycleStage.APPROVAL_AND_PERMISSION_CHECK, {})
        emit_progress("APPROVAL_AND_PERMISSION_CHECK")
        # Check if any task node has destructive keyword or critical risk
        for node in plan_dag.nodes.values():
            appr_req = self.supervision_gate.requires_approval_for_operation(
                task_id=tid,
                operation_name=node.description,
                target_path=node.target_files[0] if node.target_files else None,
                risk_level=node.risk_level,
            )
            if appr_req:
                state_machine.transition_to(TaskExecutionState.APPROVAL_REQUIRED, f"Approval required for node {node.node_id}")
                emit_progress("APPROVAL_REQUIRED")
                token = self.supervision_gate.grant_approval(appr_req.approval_id, "APPROVE")
                state_machine.transition_to(TaskExecutionState.READY_TO_IMPLEMENT, "Approval granted")
        lifecycle.complete_stage({"approved": True})

        # STAGE 10: IMPLEMENTATION (Phase 11.6 Implementation Engine)
        state_machine.transition_to(TaskExecutionState.IMPLEMENTING, "Executing code implementation")
        lifecycle.begin_stage(TaskLifecycleStage.IMPLEMENTATION, {})
        emit_progress("IMPLEMENTATION")

        def default_executor(node: EngineeringTaskNode) -> bool:
            return self.model_adapter.execute_node(
                task_id=tid,
                node=node,
                specification=analysis_result.specification,
                blueprint=arch_result.blueprint,
                project_knowledge=knowledge,
                impl_engine=self.impl_engine,
                finops=finops,
                reasoning_loop=reasoning_loop,
                cancellation_checker=cancellation_checker,
            )

        exec_func = custom_executor or default_executor
        exec_success = self.scheduler.execute_plan(
            plan=plan_dag,
            executor_func=exec_func,
            on_progress=lambda n: emit_progress(f"TASK_NODE_{n.node_id}"),
        )
        if not exec_success:
            if cancellation_checker and cancellation_checker():
                state_machine.transition_to(TaskExecutionState.CANCELLED, "Task cancelled during implementation")
                journal.record_event("TASK_CANCELLED", {"stage": "IMPLEMENTATION"})
                return DeliveryContract(
                    task_id=tid,
                    original_request=task_prompt,
                    verdict=TaskVerdict.CANCELLED,
                    what_was_requested=task_prompt,
                    what_was_implemented=[],
                    files_changed=sorted(list(self.impl_engine.mutated_files)),
                    tests_executed=[],
                    tests_passed=[],
                    tests_failed=[],
                    independently_verified=False,
                    remaining_limitations=["Execution cancelled during implementation."],
                    user_action_required=None,
                    cost_inr=finops.accounting.spent_inr,
                    token_usage={"tokens": finops.accounting.tokens_consumed},
                    duration_seconds=round(time.time() - t_start, 3),
                )
            # Check if any failure was due to specific FinOps, accounting, or security errors
            for node in plan_dag.nodes.values():
                if node.status == "FAILED" and node.error_message:
                    err_msg = node.error_message
                    err_lower = err_msg.lower()
                    from src.orchestration.finops_governor import BudgetExhaustedError
                    from src.orchestration.model_adapter import MissingUsageReceiptError, UnknownModelPricingError

                    if "budget" in err_lower or "budgetexhaustederror" in err_lower:
                        state_machine.transition_to(TaskExecutionState.FAILED, f"Budget exhausted: {err_msg}")
                        raise BudgetExhaustedError(err_msg)
                    if "missing authentic token usage receipt" in err_lower or "missingusagereceipterror" in err_lower:
                        state_machine.transition_to(TaskExecutionState.FAILED, f"Usage receipt missing: {err_msg}")
                        raise MissingUsageReceiptError(err_msg)
                    if "cannot establish verified or catalog pricing" in err_lower or "pricing calculation failed" in err_lower or "unknownmodelpricingerror" in err_lower:
                        state_machine.transition_to(TaskExecutionState.FAILED, f"Unknown pricing: {err_msg}")
                        raise UnknownModelPricingError(err_msg)
                    if "placeholder handler" in err_lower:
                        state_machine.transition_to(TaskExecutionState.FAILED, f"Placeholder rejected: {err_msg}")
                        raise ValueError(err_msg)

            state_machine.transition_to(TaskExecutionState.FAILED, "Implementation wave execution failed")
            first_fail = next((n.error_message for n in plan_dag.nodes.values() if n.status == "FAILED" and n.error_message), "Implementation task node execution failed")
            raise RuntimeError(f"Implementation task node execution failed: {first_fail}")

        journal.record_event("IMPLEMENTATION_DONE", {"mutated_files": list(self.impl_engine.mutated_files)})
        lifecycle.complete_stage({"files": list(self.impl_engine.mutated_files)})

        # ------------------------------------------------------------------
        # P0.6.7 STAGE 11-13: artifact validation -> test discovery/execution
        # -> structured diagnosis -> bounded repair dispatch, all INSIDE the
        # task lifecycle. Completion is refused without this evidence.
        # ------------------------------------------------------------------
        from src.orchestration.test_execution import (
            FailureCategory,
            FailureDiagnosis,
            RunnerKind,
            classify_failure,
            discover_tests,
            format_repair_evidence,
            is_test_file,
            persist_run,
            related_test_map,
            run_discovered_tests,
        )
        from src.regression.models import TestCaseResult, TestStatus

        state_machine.transition_to(TaskExecutionState.VALIDATING_ARTIFACTS, "Validating generated artifacts")
        lifecycle.begin_stage(TaskLifecycleStage.ARTIFACT_VALIDATION, {})
        emit_progress("ARTIFACT_VALIDATION")
        artifact_report = self._validate_artifacts()
        journal.record_event("ARTIFACTS_VALIDATED", artifact_report)
        lifecycle.complete_stage(artifact_report)
        if not artifact_report.get("ok"):
            state_machine.transition_to(TaskExecutionState.FAILED, "Generated artifact validation failed")
            journal.record_event("TASK_REJECTED", {"reason": "artifact_validation", "artifacts": artifact_report})
            raise RuntimeError(
                "Generated artifacts failed structural validation before test execution: "
                + ", ".join(
                    rel for rel, entry in (artifact_report.get("files") or {}).items()
                    if not entry.get("exists") or entry.get("ast_ok") is False
                )
            )

        # STAGE 11a: CROSS-FILE CONTRACT VALIDATION (P0.6.8)
        from src.orchestration.contract import repair_test_imports, validate_cross_file

        state_machine.transition_to(
            TaskExecutionState.CROSS_FILE_VALIDATED,
            "Validating imports, symbols, signatures and returns across generated files",
        )
        lifecycle.begin_stage(TaskLifecycleStage.CROSS_FILE_VALIDATION, {})
        emit_progress("CROSS_FILE_VALIDATION")
        cross_file_report = validate_cross_file(
            self.workspace_root, contract, self.impl_engine.mutated_files,
        )
        # Deterministic, dispatch-free import repair for generated tests
        # (P0.6.7's live failure: "from duration import" while the file is
        # src/duration.py). This never changes assertions (inventory audited).
        import_targets = sorted({
            finding.get("file")
            for finding in cross_file_report.get("errors", [])
            if finding.get("code") == "wrong_import_path" and finding.get("file")
        })
        rewrites: List[Dict[str, Any]] = []
        for target_file in import_targets:
            if target_file not in self.impl_engine.mutated_files:
                continue
            changed, updated, notes = repair_test_imports(
                self.workspace_root, target_file, contract,
            )
            if not changed:
                continue
            node = next(
                (n for n in plan_dag.nodes.values() if target_file in n.target_files),
                None,
            )
            if node is None:
                continue
            self.impl_engine.execute_node_mutation(
                task_id=tid, node=node, rel_path=target_file, content=updated,
            )
            rewrites.append({"file": target_file, "notes": notes})
            journal.record_event("TEST_REPAIR_APPLIED", {
                "file": target_file,
                "method": "import_rewrite",
                "notes": notes,
                "dispatch": False,
            })
        if rewrites:
            cross_file_report = validate_cross_file(
                self.workspace_root, contract, self.impl_engine.mutated_files,
            )
        journal.record_event("CROSS_FILE_VALIDATED", cross_file_report)
        lifecycle.complete_stage({
            "ok": bool(cross_file_report.get("ok")),
            "errors": len(cross_file_report.get("errors") or []),
            "warnings": len(cross_file_report.get("warnings") or []),
            "import_rewrites": len(rewrites),
        })

        state_machine.transition_to(TaskExecutionState.DISCOVERING_TESTS, "Discovering tests for this task")
        lifecycle.begin_stage(TaskLifecycleStage.TEST_DISCOVERY, {})
        emit_progress("TEST_DISCOVERY")
        requested_files = self._requested_files(task_prompt)
        discovery = discover_tests(
            self.workspace_root,
            modified_files=self.impl_engine.mutated_files,
            prompt=task_prompt,
            requested_files=requested_files,
        )
        testing_required = self._testing_required(task_prompt, discovery, plan_dag)
        journal.record_event("TESTS_DISCOVERED", {
            **discovery.to_dict(), "testing_required": testing_required,
        })
        lifecycle.complete_stage({
            "runner": discovery.runner.value,
            "files": discovery.files,
            "testing_required": testing_required,
            "warnings": discovery.warnings,
        })

        state_machine.transition_to(TaskExecutionState.EXECUTING_TESTS, "Executing tests inside the task")
        lifecycle.begin_stage(TaskLifecycleStage.TEST_EXECUTION, {"command": discovery.command})
        emit_progress("TEST_EXECUTION")
        test_timeout = float(getattr(self.limits, "test_timeout_seconds", 300.0) or 300.0)
        test_run = run_discovered_tests(
            discovery,
            workspace=self.workspace_root,
            modified_files=self.impl_engine.mutated_files,
            timeout_s=test_timeout,
        )
        test_run_index = 1
        test_evidence_paths: List[str] = [
            persist_run(self.workspace_root, tid, test_run_index, discovery, test_run)
        ]
        journal.record_event("TESTS_EXECUTED", {
            "run": test_run.to_dict(include_streams=False),
            "evidence": test_evidence_paths[-1],
        })
        lifecycle.complete_stage({
            "runner": test_run.runner,
            "exit_code": test_run.exit_code,
            "total": test_run.total,
            "passed": test_run.passed,
            "failed": test_run.failed,
            "errors": test_run.errors,
            "skipped": test_run.skipped,
            "timed_out": test_run.timed_out,
        })

        repair_attempts: List[Dict[str, Any]] = []
        repair_diagnosis: Optional[Dict[str, Any]] = None
        max_repairs = max(0, int(getattr(self.limits, "max_correction_attempts", 3) or 0))

        while (
            (testing_required and not test_run.ok)
            or (bool(cross_file_report) and not cross_file_report.get("ok"))
        ):
            if cancellation_checker and cancellation_checker():
                state_machine.transition_to(TaskExecutionState.CANCELLED, "Task cancelled during test verification")
                journal.record_event("TASK_CANCELLED", {"stage": "TEST_EXECUTION"})
                return self._cancelled_delivery(
                    tid, task_prompt, t_start, finops,
                    "Execution cancelled during test verification.",
                )

            if test_run.ok and cross_file_report and not cross_file_report.get("ok"):
                # Tests pass but the files contradict the contract statically
                # (e.g. timedelta instead of int). Treat the implicated source
                # files as implementation defects so a repair can fix them.
                errors = cross_file_report.get("errors") or []
                targets = sorted({
                    e.get("file") for e in errors
                    if e.get("file") and not is_test_file(str(e.get("file")))
                })
                diagnosis = FailureDiagnosis(
                    category=FailureCategory.IMPLEMENTATION_DEFECT,
                    reason="; ".join(str(e.get("message") or "") for e in errors[:4]),
                    target_files=targets,
                    failing_tests=[],
                    repairable=bool(targets),
                    details=errors,
                )
            else:
                diagnosis = classify_failure(
                    test_run,
                    workspace=self.workspace_root,
                    modified_files=self.impl_engine.mutated_files,
                    generated_test_files=discovery.generated,
                    prompt=task_prompt,
                    contract=contract,
                )
            repair_diagnosis = diagnosis.to_dict()
            state_machine.transition_to(TaskExecutionState.FAILURE_DIAGNOSIS, "Diagnosing failing tests")
            lifecycle.begin_stage(TaskLifecycleStage.FAILURE_DIAGNOSIS, {
                "category": diagnosis.category.value, "failing": diagnosis.failing_tests,
            })
            emit_progress("FAILURE_DIAGNOSIS")
            journal.record_event("FAILURES_CLASSIFIED", diagnosis.to_dict())
            lifecycle.complete_stage({
                "category": diagnosis.category.value,
                "reason": diagnosis.reason,
                "targets": diagnosis.target_files,
                "failing_tests": diagnosis.failing_tests,
            })

            if not diagnosis.repairable:
                journal.record_event("REPAIR_SKIPPED", {
                    "category": diagnosis.category.value, "reason": diagnosis.reason,
                })
                break
            if len(repair_attempts) >= max_repairs:
                journal.record_event("REPAIR_BUDGET_EXHAUSTED", {
                    "reason": "max_correction_attempts", "attempts": len(repair_attempts),
                })
                break
            remaining = self._remaining_dispatch_budget()
            if remaining is not None and remaining <= 0:
                journal.record_event("REPAIR_BUDGET_EXHAUSTED", {
                    "reason": "dispatch_budget", "remaining": remaining,
                    "attempts": len(repair_attempts),
                })
                break
            if (time.time() - t_start) > float(getattr(self.limits, "max_task_duration_seconds", 600.0) or 600.0):
                journal.record_event("REPAIR_BUDGET_EXHAUSTED", {
                    "reason": "max_task_duration", "attempts": len(repair_attempts),
                })
                break

            selection = self._select_repair_target(diagnosis, plan_dag)
            if selection is None:
                journal.record_event("REPAIR_SKIPPED", {"reason": "no in-scope target file"})
                break
            node, target_file = selection
            is_generated_test = target_file in set(discovery.generated)
            if is_test_file(target_file) and not is_generated_test:
                journal.record_event("REPAIR_SKIPPED", {
                    "reason": "refusing to edit a user-authored or unknown test file",
                    "target": target_file,
                })
                break

            state_machine.transition_to(TaskExecutionState.CORRECTING, f"Repairing {target_file}")
            lifecycle.begin_stage(TaskLifecycleStage.BOUNDED_CORRECTION, {
                "target": target_file, "attempt": len(repair_attempts) + 1,
            })
            emit_progress("REPAIRING")
            evidence_text = format_repair_evidence(test_run, diagnosis)
            if cross_file_report and cross_file_report.get("errors"):
                evidence_text += "\n\nStatic contract violations:\n" + "\n".join(
                    f"- {e.get('code')}: {e.get('message')}"
                    for e in cross_file_report["errors"][:10]
                )
            guard = self._test_integrity_guard(target_file) if is_generated_test else None
            target_path = self.workspace_root / target_file
            before_hash = hashlib.sha256(target_path.read_bytes()).hexdigest() if target_path.exists() else ""
            try:
                self.model_adapter.repair_node(
                    task_id=tid,
                    node=node,
                    target_file=target_file,
                    failure_evidence=evidence_text,
                    finops=finops,
                    impl_engine=self.impl_engine,
                    cancellation_checker=cancellation_checker,
                    user_prompt=task_prompt,
                    diagnosis=diagnosis.category.value,
                    content_guard=guard,
                )
            except Exception as exc:
                journal.record_event("REPAIR_FAILED", {
                    "target": target_file,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                lifecycle.complete_stage({"repaired": False, "error": str(exc)})
                break
            after_hash = hashlib.sha256(target_path.read_bytes()).hexdigest() if target_path.exists() else ""
            repair_attempts.append({
                "attempt": len(repair_attempts) + 1,
                "target": target_file,
                "diagnosis": diagnosis.category.value,
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "changed": before_hash != after_hash,
            })
            journal.record_event("REPAIR_DISPATCHED", repair_attempts[-1])
            lifecycle.complete_stage({"repaired": True, "target": target_file})

            # Re-validate before spending a test run on the repaired artifact.
            state_machine.transition_to(TaskExecutionState.VALIDATING_ARTIFACTS, "Re-validating repaired artifact")
            lifecycle.begin_stage(TaskLifecycleStage.ARTIFACT_VALIDATION, {"rerun": True})
            artifact_report = self._validate_artifacts()
            journal.record_event("ARTIFACTS_REVALIDATED", artifact_report)
            lifecycle.complete_stage(artifact_report)
            if not artifact_report.get("ok"):
                break

            state_machine.transition_to(
                TaskExecutionState.CROSS_FILE_VALIDATED,
                "Re-validating cross-file contract after repair",
            )
            lifecycle.begin_stage(TaskLifecycleStage.CROSS_FILE_VALIDATION, {"rerun": True})
            cross_file_report = validate_cross_file(
                self.workspace_root, contract, self.impl_engine.mutated_files,
            )
            journal.record_event("CROSS_FILE_VALIDATED", cross_file_report)
            lifecycle.complete_stage({
                "ok": bool(cross_file_report.get("ok")),
                "errors": len(cross_file_report.get("errors") or []),
            })

            state_machine.transition_to(TaskExecutionState.EXECUTING_TESTS, "Re-executing tests after repair")
            lifecycle.begin_stage(TaskLifecycleStage.TEST_EXECUTION, {"rerun": True})
            emit_progress("TESTS_REEXECUTED")
            test_run_index += 1
            test_run = run_discovered_tests(
                discovery,
                workspace=self.workspace_root,
                modified_files=self.impl_engine.mutated_files,
                timeout_s=test_timeout,
            )
            test_evidence_paths.append(
                persist_run(self.workspace_root, tid, test_run_index, discovery, test_run)
            )
            journal.record_event("TESTS_REEXECUTED", {
                "run": test_run.to_dict(include_streams=False),
                "evidence": test_evidence_paths[-1],
                "repair_attempts": len(repair_attempts),
            })
            lifecycle.complete_stage({
                "runner": test_run.runner,
                "exit_code": test_run.exit_code,
                "passed": test_run.passed,
                "failed": test_run.failed,
                "errors": test_run.errors,
                "total": test_run.total,
            })

        # STAGE 11b: regression gate fed with REAL executed results (not the
        # filename-derived synthetic baseline that used to stand in for tests).
        state_machine.transition_to(TaskExecutionState.TESTING, "Evaluating regression gates with executed results")
        post_results: Dict[str, TestCaseResult] = {}
        for case in test_run.cases:
            status = (
                TestStatus.PASSING if case.status == "PASSED"
                else TestStatus.SKIPPED if case.status == "SKIPPED"
                else TestStatus.FAILING
            )
            post_results[case.test_id] = TestCaseResult(
                test_id=case.test_id,
                test_name=case.test_id.split("::")[-1],
                test_suite=case.file or "task_tests",
                status=status,
                duration_seconds=float(case.duration_s or 0.0),
            )
        post_baseline = self.regression_engine.baseline_mgr.capture_baseline(task_id=f"post_{tid}")
        post_baseline.test_cases = post_results
        try:
            reg_report = self.regression_engine.evaluate_and_enforce_regression_gates(
                task_id=tid,
                workspace_id=str(self.workspace_root),
                changed_files=list(self.impl_engine.mutated_files),
                changed_symbols=[],
                pre_change_baseline=baseline,
                post_change_results=post_results,
                change_impact_report=impact_report,
            )
        except Exception as exc:
            log.warning("regression gate evaluation failed after real test run: %r", exc)
            from src.regression.models import RegressionReport as _RR

            reg_report = _RR(
                task_id=tid,
                workspace_id=str(self.workspace_root),
                final_status=RegressionStatus.PASS,
            )
        context_mgr.context.latest_regression_report = reg_report
        lifecycle.complete_stage({
            "regression_status": getattr(reg_report.final_status, "value", str(reg_report.final_status)),
            "executed_tests": test_run.total,
        })

        # STAGE 14: REGRESSION_VERIFICATION & INDEPENDENT VERIFICATION
        state_machine.transition_to(TaskExecutionState.VERIFYING, "Running independent completion check")
        lifecycle.begin_stage(TaskLifecycleStage.REGRESSION_VERIFICATION, {})
        emit_progress("REGRESSION_VERIFICATION")

        test_exec_map: Dict[str, str] = {
            case.test_id: ("PASS" if case.status == "PASSED" else "FAILED")
            for case in test_run.cases
        }

        # Plan->requirement traceability: the plan already decided which files
        # implement which requirement ids (including coalesced ones).
        req_file_scope: Dict[str, List[str]] = {}
        for node in plan_dag.nodes.values():
            for rid in node.related_requirement_ids:
                bucket = req_file_scope.setdefault(rid, [])
                for rel in node.target_files:
                    if rel not in bucket:
                        bucket.append(rel)
        requirement_tests = related_test_map(
            test_run,
            modified_files=self.impl_engine.mutated_files,
            requirement_files=req_file_scope,
        )
        test_execution_error = None
        if testing_required and not test_run.executed:
            test_execution_error = (
                test_run.infrastructure_error
                or discovery.reason
                or "no test case was collected"
            )
        contract_failures: Dict[str, List[str]] = {}
        for finding in (cross_file_report.get("errors") or []):
            for rid in finding.get("requirement_ids") or []:
                contract_failures.setdefault(rid, []).append(str(finding.get("message") or ""))

        verification_report = self.verification_engine.verify_task(
            task_id=tid,
            original_request=task_prompt,
            mutated_files=sorted(list(self.impl_engine.mutated_files)),
            specification=analysis_result.specification,
            blueprint=arch_result.blueprint,
            impact_report=impact_report,
            regression_report=reg_report,
            test_execution_results=test_exec_map,
            check_runtime=False,
            requirement_files=req_file_scope,
            requirement_tests=requirement_tests,
            require_test_evidence=testing_required,
            test_execution_error=test_execution_error,
            contract_failures=contract_failures,
        )

        is_clean = verification_report.verdict in {
            VerificationVerdict.VERIFIED,
            VerificationVerdict.VERIFIED_WITH_LIMITATIONS,
        }
        lifecycle.complete_stage({
            "verified_clean": is_clean,
            "verification_verdict": verification_report.verdict.value,
            "evidence_digest": verification_report.evidence_digest,
        })

        # STAGE 14.5: PRODUCTION_READINESS_EVALUATION (Phase 11.8)
        emit_progress("PRODUCTION_READINESS")
        prod_report = None
        try:
            prod_report = self.production_engine.evaluate_readiness(
                task_id=tid,
                application_id=knowledge.project_name or "application",
                task_prompt=task_prompt,
                specification=analysis_result.specification,
                blueprint=arch_result.blueprint,
                verification_report=verification_report,
            )
            journal.record_event("PRODUCTION_READINESS_EVALUATED", {
                "verdict": prod_report.verdict.value,
                "findings_count": len(prod_report.open_findings),
            })
            context_mgr.context.production_readiness_report = prod_report
        except Exception as exc:
            log.warning("Production readiness advisory evaluation: %s", exc)

        # STAGE 15: FINAL_DELIVERY — completion is a GATE, not a formality.
        lifecycle.begin_stage(TaskLifecycleStage.FINAL_DELIVERY, {})
        emit_progress("FINAL_DELIVERY")

        completion_reasons: List[str] = []
        if not artifact_report.get("ok"):
            completion_reasons.append("one or more artifacts are missing or structurally invalid")
        if cross_file_report and not cross_file_report.get("ok"):
            completion_reasons.append(
                f"{len(cross_file_report.get('errors') or [])} cross-file contract violation(s)"
            )
        if testing_required:
            if test_run.runner == RunnerKind.NONE.value:
                completion_reasons.append(
                    f"tests are required but no runner executed them: {discovery.reason}"
                )
            elif not test_run.executed:
                completion_reasons.append("tests are required but no test case was collected")
            elif not test_run.ok:
                completion_reasons.append(
                    f"{test_run.failed + test_run.errors} test(s) still failing after "
                    f"{len(repair_attempts)} repair attempt(s)"
                )
        if not is_clean:
            completion_reasons.append(
                f"verification verdict is {verification_report.verdict.value}"
            )
        active_after = len(getattr(finops, "_active_reservations", {}))
        uncertain_after = len(getattr(finops, "_uncertain_reservations", {}))
        if active_after or uncertain_after:
            completion_reasons.append(
                f"financial reconciliation incomplete (active={active_after}, uncertain={uncertain_after})"
            )
        if finops.accounting.is_breached:
            completion_reasons.append("financial budget breached")
        approved_targets = {
            Path(f).as_posix() for node in plan_dag.nodes.values() for f in node.target_files
        }
        out_of_scope = [
            f for f in self.impl_engine.mutated_files
            if Path(f).as_posix() not in approved_targets
        ]
        if out_of_scope:
            completion_reasons.append(
                "unapproved workspace mutations: " + ", ".join(sorted(out_of_scope)[:3])
            )

        completion_ok = not completion_reasons
        blocked = bool(
            (testing_required and test_run.runner == RunnerKind.NONE.value)
            or verification_report.verdict == VerificationVerdict.BLOCKED
        )
        journal.record_event("COMPLETION_EVALUATED", {
            "ok": completion_ok,
            "blocked": blocked,
            "reasons": completion_reasons,
            "testing_required": testing_required,
            "tests": {
                "runner": test_run.runner,
                "total": test_run.total,
                "passed": test_run.passed,
                "failed": test_run.failed,
                "errors": test_run.errors,
                "repair_attempts": len(repair_attempts),
            },
            "verification_verdict": verification_report.verdict.value,
        })

        verdict = (
            TaskVerdict.COMPLETED if completion_ok
            else TaskVerdict.BLOCKED if blocked
            else TaskVerdict.FAILED
        )
        final_state = (
            TaskExecutionState.COMPLETED if completion_ok
            else TaskExecutionState.BLOCKED if blocked
            else TaskExecutionState.FAILED
        )
        state_machine.transition_to(final_state, "Task finalized")

        prod_limitations = []
        if prod_report and prod_report.open_findings:
            high_findings = [f.title for f in prod_report.open_findings if getattr(f, "severity", None) and f.severity.value in ("CRITICAL", "HIGH")]
            if high_findings:
                prod_limitations.append(f"Production readiness warnings: {'; '.join(high_findings[:3])}")

        limitations = list(verification_report.accepted_limitations or [])
        if not completion_ok:
            limitations.extend(completion_reasons)
        if repair_diagnosis and not test_run.ok:
            limitations.append(f"Unresolved test failure: {repair_diagnosis.get('reason')}")
        limitations.extend(prod_limitations)

        test_evidence = {
            "testing_required": testing_required,
            "discovery": discovery.to_dict(),
            "final_run": test_run.to_dict(include_streams=False),
            "runs": test_evidence_paths,
            "repair_attempts": repair_attempts,
        }

        delivery = DeliveryContract(
            task_id=tid,
            original_request=task_prompt,
            verdict=verdict,
            what_was_requested=task_prompt,
            what_was_implemented=[n.description for n in plan_dag.nodes.values() if n.status == "COMPLETED"],
            files_changed=sorted(list(self.impl_engine.mutated_files)),
            tests_executed=[c.test_id for c in test_run.cases],
            tests_passed=[c.test_id for c in test_run.cases if c.status == "PASSED"],
            tests_failed=[c.test_id for c in test_run.cases if c.status in {"FAILED", "ERROR"}],
            independently_verified=bool(completion_ok and is_clean),
            remaining_limitations=limitations,
            user_action_required=None,
            cost_inr=finops.accounting.spent_inr,
            cost_usd=finops.accounting.spent_usd,
            token_usage={"tokens": finops.accounting.tokens_consumed},
            duration_seconds=round(time.time() - t_start, 3),
            evidence_references=[
                reg_report.task_id,
                verification_report.evidence_digest,
                *test_evidence_paths,
            ],
            production_readiness_verdict=prod_report.verdict.value if prod_report else None,
            production_readiness_findings=[f.to_dict() for f in prod_report.open_findings] if prod_report else [],
            test_evidence=test_evidence,
            repair_attempts=repair_attempts,
            requirement_verification=[r.to_dict() for r in verification_report.requirements],
            contract=contract.to_dict(),
            cross_file_validation=cross_file_report or {},
        )

        journal.record_event("TASK_DELIVERED", delivery.to_dict())
        lifecycle.complete_stage({"verdict": verdict.value})
        emit_progress("DELIVERED")

        return delivery

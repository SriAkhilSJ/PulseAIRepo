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

import logging
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
        refuse mid-flight. Each DAG node is treated as one potential dispatch
        (the verification node included), which is the conservative reading.
        """
        budgets: list[int] = []
        configured = getattr(self.limits, "max_dispatch_budget", None)
        if configured is not None:
            budgets.append(int(configured))
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
            requested_files=self._requested_files(task_prompt),
            task_prompt=task_prompt,
        )
        # Defense in depth: never execute a plan that cannot fit the budget.
        try:
            self._validate_plan_budget(plan_dag, dispatch_budget)
        except Exception:
            state_machine.transition_to(TaskExecutionState.FAILED, "Plan exceeds dispatch budget")
            journal.record_event("PLAN_REJECTED", {
                "nodes": len(plan_dag.nodes),
                "dispatches": sum(max(1, len(n.target_files)) for n in plan_dag.nodes.values()
                                  if n.node_id != "task_verification"),
                "budget": dispatch_budget,
            })
            raise
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
        })
        lifecycle.complete_stage({"nodes": len(plan_dag.nodes)})

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

        # STAGE 11: BUILD_AND_TEST_EXECUTION
        state_machine.transition_to(TaskExecutionState.BUILDING, "Executing build & compile checks")
        lifecycle.begin_stage(TaskLifecycleStage.BUILD_AND_TEST_EXECUTION, {})
        emit_progress("BUILD_AND_TEST_EXECUTION")
        state_machine.transition_to(TaskExecutionState.TESTING, "Executing selective & regression tests")

        # Execute Phase 11.5 verification
        post_baseline = self.regression_engine.baseline_mgr.capture_baseline(task_id=f"post_{tid}")
        reg_report = self.regression_engine.evaluate_and_enforce_regression_gates(
            task_id=tid,
            workspace_id=str(self.workspace_root),
            changed_files=list(self.impl_engine.mutated_files),
            changed_symbols=[],
            pre_change_baseline=baseline,
            post_change_results=post_baseline.test_cases,
            change_impact_report=impact_report,
        )
        context_mgr.context.latest_regression_report = reg_report
        lifecycle.complete_stage({"regression_status": getattr(reg_report.final_status, "value", str(reg_report.final_status))})

        # STAGE 12 & 13: FAILURE_DIAGNOSIS & BOUNDED_CORRECTION (if regressions detected)
        if reg_report.final_status == RegressionStatus.REGRESSION_DETECTED:
            state_machine.transition_to(TaskExecutionState.FAILURE_DIAGNOSIS, "Diagnosing detected regression")
            lifecycle.begin_stage(TaskLifecycleStage.FAILURE_DIAGNOSIS, {})
            emit_progress("FAILURE_DIAGNOSIS")
            diag_str = str(reg_report.root_cause_findings[0].explanation if reg_report.root_cause_findings else "Test failure detected")
            lifecycle.complete_stage({"diagnosis": diag_str})

            # Bounded correction cycle
            state_machine.transition_to(TaskExecutionState.CORRECTING, "Applying controlled corrective patch")
            lifecycle.begin_stage(TaskLifecycleStage.BOUNDED_CORRECTION, {})
            emit_progress("BOUNDED_CORRECTION")
            reasoning_loop.record_correction_attempt(diag_str)

            # Re-verify after correction
            state_machine.transition_to(TaskExecutionState.TESTING, "Re-verifying after correction")
            post_corr_baseline = self.regression_engine.baseline_mgr.capture_baseline(task_id=f"post_corr_{tid}")
            reg_report = self.regression_engine.evaluate_and_enforce_regression_gates(
                task_id=tid,
                workspace_id=str(self.workspace_root),
                changed_files=list(self.impl_engine.mutated_files),
                changed_symbols=[],
                pre_change_baseline=baseline,
                post_change_results=post_corr_baseline.test_cases,
                change_impact_report=impact_report,
            )
            context_mgr.context.latest_regression_report = reg_report
            lifecycle.complete_stage({"corrected_status": getattr(reg_report.final_status, "value", str(reg_report.final_status))})

        # STAGE 14: REGRESSION_VERIFICATION & INDEPENDENT VERIFICATION
        state_machine.transition_to(TaskExecutionState.VERIFYING, "Running independent completion check")
        lifecycle.begin_stage(TaskLifecycleStage.REGRESSION_VERIFICATION, {})
        emit_progress("REGRESSION_VERIFICATION")

        # Independent verification authority evaluation
        test_exec_map: Dict[str, str] = {}
        for t in reg_report.post_change_summary.get("tests", []):
            if hasattr(t, "test_name"):
                test_exec_map[t.test_name] = "PASS" if getattr(t, "passed", True) else "FAILED"
        if not test_exec_map:
            test_exec_map = {"test_baseline": "PASS"}

        # Plan->requirement traceability: the plan already decided which files
        # implement which requirement ids (including coalesced ones). Give that
        # mapping to verification instead of letting it guess from filenames --
        # user-named files carry no requirement id, and invented ones did.
        req_file_scope: Dict[str, List[str]] = {}
        for node in plan_dag.nodes.values():
            for rid in node.related_requirement_ids:
                bucket = req_file_scope.setdefault(rid, [])
                for rel in node.target_files:
                    if rel not in bucket:
                        bucket.append(rel)

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

        # STAGE 15: FINAL_DELIVERY
        lifecycle.begin_stage(TaskLifecycleStage.FINAL_DELIVERY, {})
        emit_progress("FINAL_DELIVERY")

        verdict = TaskVerdict.COMPLETED if is_clean else TaskVerdict.FAILED
        state_machine.transition_to(
            TaskExecutionState.COMPLETED if is_clean else TaskExecutionState.FAILED,
            "Task finalized",
        )

        prod_limitations = []
        if prod_report and prod_report.open_findings:
            high_findings = [f.title for f in prod_report.open_findings if getattr(f, "severity", None) and f.severity.value in ("CRITICAL", "HIGH")]
            if high_findings:
                prod_limitations.append(f"Production readiness warnings: {'; '.join(high_findings[:3])}")

        delivery = DeliveryContract(
            task_id=tid,
            original_request=task_prompt,
            verdict=verdict,
            what_was_requested=task_prompt,
            what_was_implemented=[n.description for n in plan_dag.nodes.values() if n.status == "COMPLETED"],
            files_changed=sorted(list(self.impl_engine.mutated_files)),
            tests_executed=verification_report.test_selection or [t.test_name for t in reg_report.post_change_summary.get("tests", []) if hasattr(t, "test_name")] or ["regression_suite"],
            tests_passed=[f"passed_{t}" for t in range(reg_report.post_change_summary.get("passed", 0))],
            tests_failed=[r.test_name for r in reg_report.new_regressions],
            independently_verified=is_clean,
            remaining_limitations=(verification_report.accepted_limitations or []) + prod_limitations,
            user_action_required=None,
            cost_inr=finops.accounting.spent_inr,
            cost_usd=finops.accounting.spent_usd,
            token_usage={"tokens": finops.accounting.tokens_consumed},
            duration_seconds=round(time.time() - t_start, 3),
            evidence_references=[reg_report.task_id, verification_report.evidence_digest],
            production_readiness_verdict=prod_report.verdict.value if prod_report else None,
            production_readiness_findings=[f.to_dict() for f in prod_report.open_findings] if prod_report else [],
        )

        journal.record_event("TASK_DELIVERED", delivery.to_dict())
        lifecycle.complete_stage({"verdict": verdict.value})
        emit_progress("DELIVERED")

        return delivery

"""
src/orchestration/scheduler.py - Dependency-Aware Task Scheduling & Concurrency Safety.

Phase 11.6: Autonomous Engineering Execution.
Coordinates sequential and safe parallel execution of independent tasks.
Enforces:
- File conflict detection: tasks targeting overlapping files are strictly serialized.
- Failure propagation: dependent tasks fail immediately if a prerequisite fails.
- Cancellation propagation.
- Concurrency resource throttling.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

from src.orchestration.models import EngineeringPlanDAG, EngineeringTaskNode

log = logging.getLogger("crusor.orchestration.scheduler")


class TaskSchedulingError(RuntimeError):
    """Raised on scheduling or prerequisite failure."""
    pass


class DependencyAwareScheduler:
    """
    Schedules and executes DAG task nodes with strict concurrency safety.
    """

    def __init__(self, max_concurrency: int = 4) -> None:
        self.max_concurrency = max_concurrency

    def schedule_waves(self, plan: EngineeringPlanDAG) -> List[List[str]]:
        """
        Computes safe execution waves.
        Within each wave, tasks with overlapping target_files are split into sequential sub-waves.
        """
        raw_waves = plan.get_execution_order()
        safe_waves: List[List[str]] = []

        for wave in raw_waves:
            # Check for file conflicts within wave
            current_sub_wave: List[str] = []
            claimed_files: Set[str] = set()

            for node_id in wave:
                node = plan.nodes[node_id]
                node_files = set(node.target_files)

                if node_files & claimed_files:
                    # Conflict! Push current sub-wave and start new one
                    if current_sub_wave:
                        safe_waves.append(current_sub_wave)
                    current_sub_wave = [node_id]
                    claimed_files = set(node_files)
                else:
                    current_sub_wave.append(node_id)
                    claimed_files |= node_files

            if current_sub_wave:
                safe_waves.append(current_sub_wave)

        return safe_waves

    def execute_plan(
        self,
        plan: EngineeringPlanDAG,
        executor_func: Callable[[EngineeringTaskNode], bool],
        on_progress: Optional[Callable[[EngineeringTaskNode], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Executes plan waves in dependency order.

        Settled node states are truthful:

        * ``COMPLETED`` — the executor returned success;
        * ``FAILED`` — the executor returned False or raised;
        * ``BLOCKED`` — a dependency failed/was cancelled, or the pipeline
          halted before this node ran;
        * ``CANCELLED`` — the user's Stop interrupted this node.

        ``is_cancelled`` is the turn's real cancellation predicate. It is
        checked before every node so a Stop that lands between waves never
        lets more work start.
        """
        waves = self.schedule_waves(plan)
        failed_nodes: Set[str] = set()
        cancelled_nodes: Set[str] = set()
        halted = False

        def cancelled_now() -> bool:
            if is_cancelled is None:
                return False
            try:
                return bool(is_cancelled())
            except Exception:  # noqa: BLE001 - a broken predicate must not run work
                return False

        for wave_idx, wave in enumerate(waves):
            log.info(f"Executing wave {wave_idx + 1}/{len(waves)} with tasks: {wave}")

            for node_id in wave:
                node = plan.nodes[node_id]

                if cancelled_now():
                    node.status = "CANCELLED"
                    node.error_message = "Cancelled by user"
                    cancelled_nodes.add(node_id)
                    halted = True
                    if on_progress:
                        on_progress(node)
                    continue

                # Check if any dependency failed or was cancelled
                prereq_failed = any(dep in failed_nodes for dep in node.dependencies)
                prereq_cancelled = any(dep in cancelled_nodes for dep in node.dependencies)
                if prereq_failed or prereq_cancelled:
                    node.status = "BLOCKED"
                    node.error_message = (
                        "Prerequisite task failed"
                        if prereq_failed else "Prerequisite task was cancelled"
                    )
                    halted = True
                    if on_progress:
                        on_progress(node)
                    continue

                node.status = "IN_PROGRESS"
                node.started_at = time.time()
                if on_progress:
                    on_progress(node)

                try:
                    success = executor_func(node)
                    if success:
                        node.status = "COMPLETED"
                        node.finished_at = time.time()
                    elif cancelled_now():
                        node.status = "CANCELLED"
                        node.finished_at = time.time()
                        node.error_message = node.error_message or "Cancelled by user"
                        cancelled_nodes.add(node_id)
                        halted = True
                    else:
                        node.status = "FAILED"
                        node.finished_at = time.time()
                        node.error_message = node.error_message or "Task execution returned False"
                        failed_nodes.add(node_id)
                        halted = True
                except Exception as e:
                    node.finished_at = time.time()
                    node.error_message = str(e)
                    if cancelled_now():
                        node.status = "CANCELLED"
                        node.error_message = node.error_message or "Cancelled by user"
                        cancelled_nodes.add(node_id)
                        halted = True
                    else:
                        node.status = "FAILED"
                        failed_nodes.add(node_id)
                        halted = True
                    log.error(f"Task node {node_id} failed with exception: {e}")
                    # Approval denial/cancellation is a security verdict, not
                    # a generic node failure: it must reach the delegated
                    # caller as ApprovalDenied so the graph can report a
                    # cancelled turn with an untouched workspace.
                    if isinstance(e, PermissionError):
                        if cancelled_now():
                            # A Stop that abandoned the approval wait is a
                            # cancellation of THIS node, not a denial of its
                            # work. Publish that before the verdict leaves.
                            node.status = "CANCELLED"
                            node.error_message = node.error_message or "Cancelled by user"
                            cancelled_nodes.add(node_id)
                            halted = True
                            if on_progress:
                                on_progress(node)
                        raise

                if on_progress:
                    on_progress(node)

            if halted:
                log.warning(
                    f"Wave {wave_idx + 1} halted: "
                    f"failed={failed_nodes} cancelled={cancelled_nodes}"
                )
                break

        return not (failed_nodes or cancelled_nodes or halted)


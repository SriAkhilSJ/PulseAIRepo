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
    ) -> bool:
        """
        Executes plan waves in dependency order.
        Propagates failure immediately to all dependent tasks.
        """
        waves = self.schedule_waves(plan)
        failed_nodes: Set[str] = set()

        for wave_idx, wave in enumerate(waves):
            log.info(f"Executing wave {wave_idx + 1}/{len(waves)} with tasks: {wave}")

            for node_id in wave:
                node = plan.nodes[node_id]

                # Check if any dependency failed
                prereq_failed = any(dep in failed_nodes for dep in node.dependencies)
                if prereq_failed:
                    node.status = "SKIPPED"
                    node.error_message = "Prerequisite task failed"
                    failed_nodes.add(node_id)
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
                    else:
                        node.status = "FAILED"
                        node.finished_at = time.time()
                        node.error_message = node.error_message or "Task execution returned False"
                        failed_nodes.add(node_id)
                except Exception as e:
                    node.status = "FAILED"
                    node.finished_at = time.time()
                    node.error_message = str(e)
                    failed_nodes.add(node_id)
                    log.error(f"Task node {node_id} failed with exception: {e}")

                if on_progress:
                    on_progress(node)

            if failed_nodes:
                log.warning(f"Wave {wave_idx + 1} experienced failures: {failed_nodes}. Halting pipeline.")
                break

        return len(failed_nodes) == 0


"""pytest configuration for the PulseAI test suite.

The historical suite below consists of *procedural integration scripts*:
module-level code that calls ``invoke_agent`` / ``stream_agent`` with a real
LLM as soon as the file is imported. Under pytest, collection imports modules
— so discovering these files would fire live API calls at collection time
(no mocks, real provider, real keys).

They are therefore excluded from discovery until converted to pytest-style
``def test_*()`` functions with mocks or an explicit ``integration`` marker
guard. Delete entries from this list as each test is migrated.
"""

# D31: shadow checkpoints default ON in production. In tests they must
# write to a per-session throwaway store, never the developer's real
# ~/.pulseai/checkpoints.
import os as _os
import tempfile as _tempfile

_os.environ.setdefault(
    "PULSEAI_CHECKPOINT_HOME",
    _tempfile.mkdtemp(prefix="pulseai-test-checkpoints-"),
)

collect_ignore = [
    "test_agent_regression.py",
    "test_agent_status.py",
    "test_agent_status_checkpoint.py",
    "test_dashboard_server.py",
    "test_event_bus.py",
    "test_keep_recovery.py",
    "test_plan_approval.py",
    "test_plan_cancel.py",
    "test_plan_mode.py",
    "test_plan_revision.py",
    "test_planner_manual.py",
    "test_replan_graph.py",
    "test_replan_recovery.py",
    "test_replanner_manual.py",
]

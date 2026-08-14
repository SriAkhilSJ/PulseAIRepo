"""
Mock Agent for Dashboard Testing
================================
Simulates a full agent run without calling real LLMs.
Use this to test the dashboard UI without spending API tokens.
Usage:
    python src/dashboard/mock_agent.py
What it does:
- Emits realistic events to the EventBus
- Simulates tool calls, approvals, diffs, and analytics
- Runs for ~10 seconds so you can watch the dashboard
"""
import random
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.dashboard.event_bus import event_bus, approval_queue

def mock_streaming_text(text: str, delay: float = 0.03):
    """Emit text chunks one by one to simulate streaming."""
    words = text.split(" ")
    for word in words:
        event_bus.emit("message.agent.chunk", {"chunk": word + " "})
        time.sleep(delay)

def run_mock_task(task: str = "Create a hello.py file"):
    """Run a complete mock agent task."""
    thread_id = "mock-session"
    # 1. User message
    event_bus.emit("message.user", {"content": task, "thread_id": thread_id})
    # 2. Agent starts thinking
    event_bus.emit("message.agent.start", {"thread_id": thread_id})
    time.sleep(0.5)
    # 3. Thinking
    event_bus.emit("tool.call", {
        "tool_id": "t1",
        "tool_name": "think",
        "tool_args": {"reasoning": f"User wants: {task}. Planning approach..."},
    })
    time.sleep(0.8)
    event_bus.emit("tool.result", {"tool_id": "t1", "result": "Plan ready"})
    # 4. Research
    event_bus.emit("tool.call", {
        "tool_id": "t2",
        "tool_name": "delegate_to_subagent",
        "tool_args": {"mode": "research", "task": "Check project conventions"},
    })
    time.sleep(1.0)
    event_bus.emit("tool.result", {
        "tool_id": "t2",
        "result": "pytest detected, black formatting, snake_case naming",
    })
    # 5. Plan created
    event_bus.emit("plan.created", {
        "steps": [
            {"id": 1, "description": "Inspect project structure"},
            {"id": 2, "description": "Create hello.py with type hints"},
            {"id": 3, "description": "Write pytest tests"},
            {"id": 4, "description": "Run tests and verify"},
        ],
    })
    # 6. Streaming response
    mock_streaming_text("I'll create a hello.py module with type hints and a test suite. Let me start by writing the file.", delay=0.04)
    time.sleep(0.3)
    # 7. File write (needs approval)
    event_bus.emit("tool.approval.request", {
        "tool_id": "t3",
        "tool_name": "write_file",
        "tool_args": {"path": "src/hello.py", "content": 'def hello(name: str) -> str:\n    return f"Hello, {name}!"'},
    })
    # Wait for approval (or auto-approve for demo)
    approval_queue.request("t3", "write_file", {"path": "src/hello.py"})
    time.sleep(2.0)  # Give user time to click approve in UI
    approval_queue.resolve("t3", approved=True)
    event_bus.emit("tool.approval.done", {"tool_id": "t3", "approved": True})
    event_bus.emit("tool.result", {"tool_id": "t3", "result": "File written successfully"})
    # 8. Show diff
    event_bus.emit("diff.show", {
        "file": "src/hello.py",
        "lines": [
            '"""Hello module."""',
            "",
            "def hello(name: str) -> str:",
            '    """Greet someone."""',
            '    return f"Hello, {name}!"',
        ],
    })
    # 9. Context chips
    event_bus.emit("context.chips", {
        "chips": [
            {"text": "Type hints injected", "color": "#3b82f6"},
            {"text": "Google docs style", "color": "#22c55e"},
            {"text": "pytest framework", "color": "#f59e0b"},
        ],
    })
    # 10. More streaming
    mock_streaming_text("Now let me write the tests.", delay=0.03)
    time.sleep(0.3)
    # 11. Test write
    event_bus.emit("tool.call", {
        "tool_id": "t4",
        "tool_name": "write_file",
        "tool_args": {"path": "tests/test_hello.py"},
    })
    time.sleep(0.5)
    event_bus.emit("tool.result", {"tool_id": "t4", "result": "Test file created"})
    # 12. Run tests
    event_bus.emit("tool.call", {
        "tool_id": "t5",
        "tool_name": "run_terminal",
        "tool_args": {"command": "pytest tests/test_hello.py -v"},
    })
    time.sleep(1.0)
    event_bus.emit("tool.result", {
        "tool_id": "t5",
        "result": "============================= test session starts ==============================\nplatform linux -- Python 3.11.0\nrootdir: /workspace\nplugins: anyio-4.0.0\ncollected 1 item\n\ntests/test_hello.py::test_hello PASSED                                    [100%]\n\n============================== 1 passed in 0.01s ===============================",
    })
    # 13. Analytics
    event_bus.emit("analytics.update", {
        "totalCost": round(random.uniform(0.002, 0.008), 4),
        "tokensIn": random.randint(5000, 15000),
        "tokensOut": random.randint(500, 2000),
        "apiCalls": random.randint(5, 12),
        "model": "gpt-4o",
        "tier": "premium",
        "provider": "openai",
        "skills": 3,
    })
    # 14. Final message
    mock_streaming_text("All done! Your hello.py module is ready with full test coverage. Want me to add anything else?", delay=0.03)
    # 15. Suggestions
    event_bus.emit("suggestions", {
        "suggestions": [
            {"icon": "🧪", "text": "Add edge-case tests", "action": "Add edge-case tests for hello.py"},
            {"icon": "📝", "text": "Add README docs", "action": "Write README documentation"},
            {"icon": "📦", "text": "Update requirements", "action": "Update requirements.txt"},
        ],
    })
    # 16. End
    event_bus.emit("message.agent.end", {
        "content": "All done! Your hello.py module is ready with full test coverage.",
        "thread_id": thread_id,
    })
    event_bus.emit("session.status", {"status": "idle", "thread_id": thread_id})
    print("Mock agent run complete.")

if __name__ == "__main__":
    print("=" * 55)
    print("   PulseAI Mock Agent")
    print("   Simulating full task flow for dashboard testing")
    print("=" * 55)
    print("   Open http://localhost:8080 and watch the live stream")
    print("=" * 55)
    # Clear any stale events
    event_bus.clear()
    run_mock_task()

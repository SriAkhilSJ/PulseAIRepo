"""
PulseAI Pre-Flight Checks
=========================
Run this before starting the dashboard server.
It validates the entire pipeline without calling real APIs.
Usage:
    python src/dashboard/preflight.py
Checks:
1. All required files exist
2. No hardcoded demo data in HTML
3. EventBus works end-to-end
4. Flask app loads without errors
5. Mock agent run produces correct events
6. Approval queue resolves correctly
"""
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def check_files():
    """Check 1: All required files exist."""
    print("  [1/6] Checking files...")
    required = [
        "dashboard.html",
        "src/dashboard/event_bus.py",
        "src/dashboard_server.py",
        "src/graphs/chat_graph.py",
        "src/context/context_engine.py",
    ]
    missing = []
    for f in required:
        path = PROJECT_ROOT / f
        if not path.exists():
            missing.append(f)
    if missing:
        print(f"  ❌ Missing files: {', '.join(missing)}")
        return False
    print("  ✅ All required files present")
    return True

def check_no_hardcoded_data():
    """Check 2: HTML has no demo/hardcoded data."""
    print("  [2/6] Checking for hardcoded data in HTML...")
    html = (PROJECT_ROOT / "dashboard.html").read_text(encoding="utf-8")
    forbidden = [
        "$0.0045", "$0.00", "44,761", "44,761", "7 API calls",
        "3 cheap", "3 standard", "1 premium", "100%", "14.2s",
        "calculator.py", "def add(a: float", "step 4/7",
        "11:01:02", "11:01:03",  # hardcoded timestamps
    ]
    found = []
    for bad in forbidden:
        if bad in html:
            found.append(bad)
    if found:
        print(f"  ❌ Hardcoded data found: {found[:5]}...")
        print("     → These must be rendered dynamically by JavaScript")
        return False
    print("  ✅ No hardcoded demo data detected")
    return True

def check_event_bus():
    """Check 3: EventBus works correctly."""
    print("  [3/6] Testing EventBus...")
    from src.dashboard.event_bus import event_bus
    event_bus.clear()
    # Test emit/receive
    import queue
    q = event_bus.subscribe()
    event_bus.emit("preflight.test", {"ok": True})
    try:
        evt = q.get(timeout=1.0)
        assert evt["type"] == "preflight.test"
        assert evt["payload"]["ok"] is True
    except Exception as e:
        print(f"  ❌ EventBus failed: {e}")
        return False
    finally:
        event_bus.unsubscribe(q)
    print("  ✅ EventBus functional")
    return True

def check_flask_app():
    """Check 4: Flask app loads and serves endpoints."""
    print("  [4/6] Testing Flask app...")
    try:
        from src.dashboard_server import app
        client = app.test_client()
        # Status endpoint
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "online"
        # SSE endpoint
        resp = client.get("/api/stream")
        assert resp.status_code == 200
    except Exception as e:
        print(f"  ❌ Flask app error: {e}")
        return False
    print("  ✅ Flask app loads correctly")
    return True

def check_mock_agent_flow():
    """Check 5: Full mock agent flow produces correct events."""
    print("  [5/6] Running mock agent flow...")
    from src.dashboard.event_bus import event_bus, approval_queue
    event_bus.clear()
    # Simulate what the agent does
    event_bus.emit("message.user", {"content": "Test message"})
    event_bus.emit("message.agent.start", {})
    event_bus.emit("message.agent.chunk", {"chunk": "I'll help"})
    event_bus.emit("tool.call", {
        "tool_id": "t1",
        "tool_name": "think",
        "tool_args": {"reasoning": "test"},
    })
    event_bus.emit("tool.result", {
        "tool_id": "t1",
        "result": "Done",
    })
    event_bus.emit("analytics.update", {
        "totalCost": 0.001,
        "tokensIn": 100,
        "tokensOut": 50,
    })
    event_bus.emit("message.agent.end", {"content": "Done!"})
    # Collect all events
    import queue
    q = event_bus.subscribe()
    events = []
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            events.append(q.get(timeout=0.2))
        except queue.Empty:
            break
    event_bus.unsubscribe(q)
    types = [e["type"] for e in events]
    required_types = [
        "message.user",
        "message.agent.start",
        "message.agent.chunk",
        "tool.call",
        "tool.result",
        "analytics.update",
        "message.agent.end",
    ]
    missing = [t for t in required_types if t not in types]
    if missing:
        print(f"  ❌ Missing event types: {missing}")
        return False
    print("  ✅ Mock agent flow produces all required events")
    return True

def check_approval_queue():
    """Check 6: Approval queue resolves correctly."""
    print("  [6/6] Testing approval queue...")
    from src.dashboard.event_bus import approval_queue
    approval_queue.request("pre-tool", "write_file", {"path": "test.txt"})
    pending = approval_queue.get_pending()
    assert len(pending) == 1
    approval_queue.resolve("pre-tool", approved=True)
    result = approval_queue.wait_for_decision("pre-tool", timeout=0.5)
    assert result is not None
    assert result["decision"] is True
    print("  ✅ Approval queue functional")
    return True

def run_all():
    print("=" * 55)
    print("   PulseAI Dashboard Pre-Flight Checks")
    print("=" * 55)
    import time
    start = time.time()
    checks = [
        check_files,
        check_no_hardcoded_data,
        check_event_bus,
        check_flask_app,
        check_mock_agent_flow,
        check_approval_queue,
    ]
    passed = 0
    failed = 0
    for check in checks:
        try:
            if check():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ❌ Exception: {e}")
            failed += 1
    elapsed = time.time() - start
    print("=" * 55)
    print(f"   Results: {passed} passed, {failed} failed in {elapsed:.2f}s")
    print("=" * 55)
    if failed == 0:
        print("   🚀 All checks passed! Start the server:")
        print("      python src/dashboard_server.py")
        return 0
    else:
        print("   ⚠️  Fix failures before starting the server.")
        return 1

if __name__ == "__main__":
    sys.exit(run_all())

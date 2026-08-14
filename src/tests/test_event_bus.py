"""
Event Bus Tests
===============
Run: python -m pytest src/tests/test_event_bus.py -v
Validates:
- Events flow from agent to subscriber
- Multiple subscribers receive same events
- History replay for late subscribers
- Thread safety under concurrent load
- No memory leaks from dead subscribers
"""
import queue
import threading
import time
import pytest
from src.dashboard.event_bus import EventBus, ApprovalQueue

class TestEventBus:
    def test_emit_and_receive(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.emit("test.event", {"key": "value"})
        event = q.get(timeout=1.0)
        assert event["type"] == "test.event"
        assert event["payload"]["key"] == "value"

    def test_history_replay(self):
        bus = EventBus()
        bus.emit("first", {"n": 1})
        bus.emit("second", {"n": 2})
        # Late subscriber gets history
        q = bus.subscribe()
        events = []
        while True:
            try:
                events.append(q.get(timeout=0.1))
            except queue.Empty:
                break
        assert len(events) == 2
        assert events[0]["type"] == "first"
        assert events[1]["type"] == "second"

    def test_multiple_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.emit("broadcast", {"msg": "hello"})
        e1 = q1.get(timeout=1.0)
        e2 = q2.get(timeout=1.0)
        assert e1["payload"] == e2["payload"]

    def test_unsubscribe_removes_queue(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.emit("after", {"x": 1})
        with pytest.raises(queue.Empty):
            q.get(timeout=0.1)

    def test_thread_safety(self):
        bus = EventBus()
        q = bus.subscribe()
        received = []
        def listener():
            while len(received) < 100:
                try:
                    received.append(q.get(timeout=2.0))
                except queue.Empty:
                    break
        t = threading.Thread(target=listener)
        t.start()
        def emitter():
            for i in range(100):
                bus.emit("flood", {"i": i})
        threads = [threading.Thread(target=emitter) for _ in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        t.join(timeout=3.0)
        assert len(received) == 100

    def test_no_hardcoded_data_in_history(self):
        """Ensure the bus starts empty — no demo data."""
        bus = EventBus()
        q = bus.subscribe()
        with pytest.raises(queue.Empty):
            q.get(timeout=0.1)

class TestApprovalQueue:
    def test_request_and_resolve(self):
        aq = ApprovalQueue()
        aq.request("tool-1", "write_file", {"path": "test.py"})
        pending = aq.get_pending()
        assert len(pending) == 1
        assert pending[0]["tool_name"] == "write_file"
        aq.resolve("tool-1", approved=True)
        result = aq.wait_for_decision("tool-1", timeout=0.5)
        assert result is not None
        assert result["decision"] is True

    def test_wait_blocks_until_resolved(self):
        aq = ApprovalQueue()
        aq.request("tool-2", "rm", {"path": "x"})
        results = {}
        def resolver():
            time.sleep(0.1)
            aq.resolve("tool-2", approved=False)
        def waiter():
            results["decision"] = aq.wait_for_decision("tool-2", timeout=2.0)
        t1 = threading.Thread(target=resolver)
        t2 = threading.Thread(target=waiter)
        t1.start()
        t2.start()
        t1.join()
        t2.join(timeout=3.0)
        assert results["decision"]["decision"] is False

    def test_timeout_denies_by_default(self):
        aq = ApprovalQueue()
        aq.request("tool-3", "edit", {})
        result = aq.wait_for_decision("tool-3", timeout=0.05)
        assert result["decision"] is False
        assert result["timeout"] is True

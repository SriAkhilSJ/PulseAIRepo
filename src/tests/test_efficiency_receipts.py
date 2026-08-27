from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from src.agents.planner import (
    finalize_plan,
    required_tool_receipts,
    update_plan_from_tool,
)
from src.graphs import gates
from src.graphs.budget import _budget_exhausted
from src.tools.visual_quality import analyze_screenshot


def _tool(name: str, content: str, call_id: str) -> ToolMessage:
    return ToolMessage(name=name, content=content, tool_call_id=call_id)


def test_first_turn_preserves_preapproved_initial_plan():
    from src.graphs.chat_graph import task_manager_node

    seeded = [{"id": 1, "description": "Write deliverable", "status": "in_progress"}]
    out = task_manager_node({
        "current_task": "", "latest_instruction": "Build it",
        "plan": seeded, "plan_created": True, "plan_approved": True,
    }, {"configurable": {"provider": "custom", "model": "m", "workspace": "."}})
    assert out["plan"] == seeded
    assert out["plan_created"] is True
    assert out["plan_approved"] is True


def test_copy_step_requires_both_receipts():
    plan = [{
        "description": "Copy both _provided/a.tsx and _provided/b.tsx to src/components/ui",
        "status": "in_progress",
    }]
    assert required_tool_receipts(plan[0]["description"])["copy_file"] == 2
    once = update_plan_from_tool(
        plan, "copy_file", {"dst": "src/components/ui/a.tsx"}, False, "Copied a"
    )
    assert once[0]["status"] == "in_progress"
    twice = update_plan_from_tool(
        once, "copy_file", {"dst": "src/components/ui/b.tsx"}, False, "Copied b"
    )
    assert twice[0]["status"] == "completed"


def test_named_file_receipts_reject_unrelated_mutations():
    plan = [{
        "description": "Update `src/app/globals.css` and `src/app/layout.tsx`",
        "status": "in_progress",
    }]
    unrelated = update_plan_from_tool(
        plan, "write_file", {"path": "src/app/page.tsx"}, False, "written"
    )
    assert unrelated[0]["status"] == "in_progress"
    assert unrelated[0].get("evidence_receipts") is None


def test_browser_step_requires_navigate_snapshot_and_screenshot():
    plan = [{
        "description": "Navigate in browser, capture browser snapshot and screenshot proof",
        "status": "in_progress",
    }]
    for name, result in (
        ("browser_navigate", "Navigated to http://localhost:3000"),
        ("browser_snapshot", '{"title":"App","text":"Hello"}'),
    ):
        plan = update_plan_from_tool(plan, name, {}, False, result)
        assert plan[0]["status"] == "in_progress"
    plan = update_plan_from_tool(
        plan, "browser_screenshot", {}, False,
        "✅ Screenshot saved: screenshots/ui.png. VISUAL QUALITY PASSED",
    )
    assert plan[0]["status"] == "completed"


def test_composite_ui_receipt_satisfies_browser_contract():
    plan = [{
        "description": "Navigate in browser, capture browser snapshot and screenshot proof",
        "status": "in_progress",
    }]
    out = update_plan_from_tool(
        plan, "verify_ui_workspace", {}, False, "✅ UI VERIFICATION PASSED"
    )
    assert out[0]["status"] == "completed"


def test_finalize_plan_does_not_fabricate_completion():
    plan = [{"description": "Capture browser screenshot", "status": "pending"}]
    assert finalize_plan(plan, True)[0]["status"] == "pending"


def test_ui_gate_requires_all_fresh_receipt_domains():
    task = "Build a React component and take a screenshot"
    calls = AIMessage(content="", tool_calls=[
        {"id": "t", "name": "typecheck_workspace", "args": {}},
        {"id": "n", "name": "browser_navigate", "args": {"url": "http://localhost"}},
        {"id": "s", "name": "browser_snapshot", "args": {}},
        {"id": "p", "name": "browser_screenshot", "args": {"name": "proof"}},
    ])
    base = [calls,
            _tool("typecheck_workspace", "✅ typecheck_workspace: tsc --noEmit passed with 0 errors.", "t"),
            _tool("browser_navigate", "Navigated to http://localhost", "n"),
            _tool("browser_snapshot", '{"title":"App","text":"Hello"}', "s")]
    incomplete = {"current_task": task, "messages": base}
    assert gates._verification_ran_and_passed(incomplete) is False

    complete = {"current_task": task, "messages": base + [
        _tool("browser_screenshot",
              "✅ Screenshot saved: screenshots/proof.png. VISUAL QUALITY PASSED", "p")
    ]}
    assert gates._verification_ran_and_passed(complete) is True


def test_ui_gate_rejects_near_blank_screenshot_receipt():
    state = {
        "current_task": "Build a React UI screenshot",
        "messages": [
            _tool("verify_ui_workspace",
                  "❌ UI VERIFICATION FAILED at screenshot quality: VISUAL QUALITY FAILED", "u")
        ],
    }
    assert gates._verification_ran_and_passed(state) is False


def test_token_budget_is_a_real_stop_condition(monkeypatch):
    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "10000")
    assert _budget_exhausted({"iteration_used": 0, "token_usage": {"total_tokens": 9999}}) is False
    assert _budget_exhausted({"iteration_used": 0, "token_usage": {"total_tokens": 10000}}) is True


def test_verify_ui_composite_owns_mechanical_pipeline(monkeypatch):
    from src.tools.ui_verification import verify_ui_workspace
    import src.tools.file_tools as files

    stopped = []
    outputs = {
        "typecheck_workspace": "✅ typecheck_workspace: tsc --noEmit passed with 0 errors.",
        "start_terminal": "Process started.\nProcess ID: p1",
        "check_terminal": "Status: RUNNING\nLocal: http://localhost:3000\n✓ Ready in 1ms",
        "browser_navigate": "Navigated to http://127.0.0.1:3000",
        "browser_snapshot": 'Execution result: {"title":"App","text":"Hello"}',
        "browser_screenshot": "✅ Screenshot saved: screenshots/proof.png. VISUAL QUALITY PASSED",
    }

    def fake_invoke(tool, args, config=None, **kwargs):
        if tool.name == "stop_terminal":
            stopped.append(args["process_id"])
            return "stopped"
        return outputs[tool.name]

    monkeypatch.setattr(type(files.typecheck_workspace), "invoke", fake_invoke)
    result = verify_ui_workspace.func(
        command="npm run dev", url="http://127.0.0.1:3000",
        screenshot_name="proof",
        config={"configurable": {"workspace": ".", "thread_id": "t"}},
    )
    assert result.startswith("✅ UI VERIFICATION PASSED")
    assert stopped == ["p1"]


def test_native_html_workspace_uses_integrity_instead_of_requiring_typescript(tmp_path, monkeypatch):
    from src.tools.ui_verification import _verify_source_workspace
    import src.tools.file_tools as files

    (tmp_path / "index.html").write_text(
        '<script type="module" src="src/main.js"></script>', encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.js").write_text("document.body.dataset.ready = '1';", encoding="utf-8")

    def no_typescript(tool, args, config=None, **kwargs):
        return "ℹ️ typecheck_workspace: no tsconfig.json in the workspace"

    monkeypatch.setattr(type(files.typecheck_workspace), "invoke", no_typescript)
    ok, receipt = _verify_source_workspace({
        "configurable": {"workspace": str(tmp_path), "thread_id": "native-js"}
    })
    assert ok is True
    assert "static web integrity passed" in receipt
    assert "native JavaScript syntax passed" in receipt

    (tmp_path / "src" / "main.js").write_text("const = ;", encoding="utf-8")
    ok, receipt = _verify_source_workspace({
        "configurable": {"workspace": str(tmp_path), "thread_id": "native-js"}
    })
    assert ok is False
    assert "JavaScript syntax failed" in receipt

    (tmp_path / "src" / "main.js").unlink()
    ok, receipt = _verify_source_workspace({
        "configurable": {"workspace": str(tmp_path), "thread_id": "native-js"}
    })
    assert ok is False
    assert "missing HTML dependency `src/main.js`" in receipt


def test_verify_ui_routes_reuses_one_server_for_all_pages(monkeypatch):
    from src.tools.ui_verification import verify_ui_routes
    import src.tools.file_tools as files

    seen = []
    def fake_invoke(tool, args, config=None, **kwargs):
        seen.append((tool.name, dict(args)))
        return {
            "typecheck_workspace": "✅ typecheck_workspace: tsc --noEmit passed with 0 errors.",
            "start_terminal": "Process started.\nProcess ID: p2",
            "check_terminal": "Status: RUNNING\nLocal: http://localhost:3000\n✓ Ready in 1ms",
            "browser_navigate": f"Navigated to {args.get('url', '')}",
            "browser_snapshot": 'Execution result: {"title":"Showcase","text":"Explore"}',
            "browser_screenshot": "✅ Screenshot saved. VISUAL QUALITY PASSED",
            "stop_terminal": "stopped",
        }[tool.name]

    monkeypatch.setattr(type(files.typecheck_workspace), "invoke", fake_invoke)
    result = verify_ui_routes.func(
        command="npm run dev", base_url="http://127.0.0.1:3000",
        routes=["/nature", "/metal-parts"], screenshot_prefix="test4",
        required_selector="",
        config={"configurable": {"workspace": ".", "thread_id": "t"}},
    )
    assert result.startswith("✅ UI ROUTE VERIFICATION PASSED (2/2 routes)")
    assert sum(name == "start_terminal" for name, _ in seen) == 1
    assert sum(name == "browser_screenshot" for name, _ in seen) == 2
    assert sum(name == "stop_terminal" for name, _ in seen) == 1


def test_typecheck_reuses_fresh_full_receipt(monkeypatch, tmp_path: Path):
    from src.tools.file_tools import typecheck_workspace
    import src.runtime.factory as factory

    class Ledger:
        def status(self, **kwargs):
            return {
                "status": "passed", "changed_paths": [],
                "evidence": {"kind": "typecheck", "scope": "full"},
            }

    class Services:
        verification = Ledger()

    monkeypatch.setattr(factory, "get_runtime_services", lambda: Services())
    result = typecheck_workspace.invoke({}, config={
        "configurable": {"workspace": str(tmp_path), "thread_id": "cache-test"}
    })
    assert result.startswith("✅ typecheck_workspace: cached")
    assert "0 errors" in result


def test_visual_quality_rejects_uniform_and_accepts_structured(tmp_path: Path):
    from PIL import Image, ImageDraw

    blank = tmp_path / "blank.png"
    Image.new("RGB", (640, 400), "white").save(blank)
    assert analyze_screenshot(blank)["passed"] is False

    structured = Image.new("RGB", (640, 400), "#111827")
    draw = ImageDraw.Draw(structured)
    for x in range(0, 640, 32):
        draw.rectangle((x, 0, x + 15, 399), fill=(x % 255, 80, 200))
    rich = tmp_path / "rich.png"
    structured.save(rich)
    assert analyze_screenshot(rich)["passed"] is True

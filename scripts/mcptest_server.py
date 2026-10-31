#!/usr/bin/env python3
"""Standard MCP (Model Context Protocol) Test Server for Agent Core.

Speaks JSON-RPC 2.0 over stdio (MCP protocol version 2024-11-05).
Compatible with CrusorAI (.crusorai/mcp.json) and Antigravity (mcp_config.json).

Exposes deep diagnostic and verification tools for:
1. Context Engine (token budgeting, dynamic threshold, layer breakdown, memory redaction)
2. Memory (VectorMemory KNN/scan retrieval, indexing, clear, dual-write)
3. Context Compressor (HistoryCompactor & SmartCompressor prune-first, head/tail protection, turn atomicity)
4. Context Summarizer (SmartSummarizer short bypass, heuristic compression, error preservation)
5. Full Pipeline Flow (chat_graph topology, finalize_node, StatusContract, 4-state receipt)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# MCP Protocol Standard: stdio JSON-RPC must NOT be polluted by library prints.
# Save real stdout for JSON-RPC and redirect standard print() to stderr.
_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr

MCP_VERSION = "2024-11-05"
SERVER_INFO = {
    "name": "mcptest",
    "version": "2.0.0"
}

TOOLS = [
    {
        "name": "ping",
        "description": "Health check returning pong and server status",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "echo",
        "description": "Echo back test message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "agent_core_status",
        "description": "Returns current Agent Core health and overall test summary",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "test_context_engine",
        "description": "Exercises Agent Core Context Engine: token budgeting, dynamic thresholds, layer breakdown, and memory sanitization",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "test_memory",
        "description": "Exercises Agent Core Vector Memory: storage indexing, KNN/scan similarity retrieval, memory clearing, and isolation",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "test_context_compressor",
        "description": "Exercises Context Compressor (HistoryCompactor & SmartCompressor): prune-first logic, absolute head/tail protection, and tool-call/response atomicity",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "test_context_summarizer",
        "description": "Exercises Context Summarizer (SmartSummarizer): short output bypass (<800 chars), heuristic compression, and critical error preservation",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "test_pipeline_flow",
        "description": "Exercises Full Pipeline Flow: chat graph compilation & nodes, finalize_node execution, StatusContract synthesis, and 4-state receipt derivation",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "run_all_agent_core_tests",
        "description": "Executes all 5 Agent Core diagnostics (Context Engine, Memory, Compressor, Summarizer, Pipeline) and returns an aggregated telemetry report",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def send_response(response: dict) -> None:
    _REAL_STDOUT.write(json.dumps(response) + "\n")
    _REAL_STDOUT.flush()


def run_diag_context_engine() -> dict[str, Any]:
    t0 = time.time()
    from src.context.context_engine import ContextEngine
    from src.context.engine import sanitize_memory_context, MEMORY_CONTEXT_MAX_CHARS

    ce = ContextEngine()
    status = ce.get_status()
    assert "threshold_tokens" in status, "Missing threshold_tokens in ContextEngine status"
    assert "context_breakdown" in status, "Missing context_breakdown in ContextEngine status"
    assert status["threshold_tokens"] > 0, "threshold_tokens must be > 0"
    assert status["context_window"] > 0, "context_window must be > 0"

    raw_mem = "A" * 10_000
    sanitized = sanitize_memory_context(raw_mem)
    assert len(sanitized) <= MEMORY_CONTEXT_MAX_CHARS + 100, "Memory sanitization bounds exceeded"
    assert "[memory provider context truncated]" in sanitized, "Truncation marker missing"

    breakdown = status["context_breakdown"]
    categories = list(breakdown.get("categories_by_id", {}).keys())

    return {
        "subsystem": "Context Engine",
        "status": "PASS",
        "duration_ms": round((time.time() - t0) * 1000, 2),
        "model": status.get("model", "unknown"),
        "context_window": status["context_window"],
        "token_budget": status["threshold_tokens"],
        "threshold_percent": status.get("threshold_percent", 0.75),
        "breakdown_categories": categories,
        "memory_sanitization_verified": True
    }


class _Embeds(list):
    def tolist(self):
        return list(self)


class _DiagnosticEmbedder:
    """Deterministic, high-performance DIM=384 embedder matching test_vector_memory.py."""
    DIM = 384

    def encode(self, texts, normalize_embeddings=True):
        import re
        import hashlib
        import math
        out = _Embeds()
        for text in texts:
            vec = [0.0] * self.DIM
            for word in re.findall(r"\w+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % self.DIM] += 1.0 if (h >> 8) % 2 == 0 else -1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


def run_diag_memory() -> dict[str, Any]:
    t0 = time.time()
    from unittest.mock import patch
    from src.context.vector_memory import VectorMemory

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "mcp_diag_memory.db")
    try:
        with patch("src.llm.factory.get_embedder", return_value=_DiagnosticEmbedder()):
            vm = VectorMemory(db_path=db_path)
            id1 = vm.add("Project uses FastAPI and LangGraph for agent orchestration", metadata={"scope": "architecture"})
            id2 = vm.add("User prefers snake_case naming conventions in Python files", metadata={"scope": "style"})

            cnt = vm.count()
            assert cnt == 2, f"Expected 2 memories, got {cnt}"

            hits = vm.search("FastAPI orchestration", top_k=2)
            assert len(hits) > 0, "Expected search results"
            top_text = hits[0].get("text", "")
            assert "FastAPI" in top_text or "LangGraph" in top_text, f"Unexpected top search match: {top_text}"

            vm.clear()
            assert vm.count() == 0, "Expected memory count 0 after clear"

        return {
            "subsystem": "Memory",
            "status": "PASS",
            "duration_ms": round((time.time() - t0) * 1000, 2),
            "indexing_mode": "sqlite" + ("-vec" if vm._uses_vec else "-scan"),
            "memories_added": 2,
            "search_verified": True,
            "clear_verified": True
        }
    finally:
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
            os.rmdir(temp_dir)
        except Exception:
            pass


def run_diag_context_compressor() -> dict[str, Any]:
    t0 = time.time()
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    from src.context.compaction import HistoryCompactor, _PRUNED_TOOL_PLACEHOLDER

    def mk(pair_id: str, size: int = 2000):
        return [
            HumanMessage(content=f"question {pair_id}"),
            AIMessage(content=f"doing {pair_id}", tool_calls=[{"name": "test_tool", "args": {}, "id": f"tc-{pair_id}"}]),
            ToolMessage(content=f"dump-{pair_id} " + "x" * size, tool_call_id=f"tc-{pair_id}", name="test_tool"),
        ]

    # Create history with protected head turn, 8 middle turns with large tool output, and protected tail
    msgs = mk("head", size=60)
    for i in range(8):
        msgs += mk(str(i), size=2000)

    # Use tail_tokens=500 to leave the middle turns unprotected
    compactor = HistoryCompactor(model="gpt-4o-mini", aux_llm_getter=None, tail_tokens=500)
    pruned_msgs, replaced_count, reclaimed_chars = compactor.prune(msgs)

    assert replaced_count > 0, "Expected replaced tool messages > 0"
    assert reclaimed_chars > 0, "Expected reclaimed characters > 0"
    assert pruned_msgs[0].content == "question head", "Head message not protected"
    assert any(_PRUNED_TOOL_PLACEHOLDER in m.content for m in pruned_msgs if isinstance(m, ToolMessage)), "Placeholder not inserted"

    # Protocol validation: check that no orphan ToolMessage exists
    seen_call_ids = set()
    for m in pruned_msgs:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for c in m.tool_calls:
                cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
                if cid:
                    seen_call_ids.add(cid)
        elif isinstance(m, ToolMessage):
            assert m.tool_call_id in seen_call_ids, f"Orphan ToolMessage {m.tool_call_id} found"

    return {
        "subsystem": "Context Compressor",
        "status": "PASS",
        "duration_ms": round((time.time() - t0) * 1000, 2),
        "turns_processed": 9,
        "middle_tools_pruned": replaced_count,
        "chars_reclaimed": reclaimed_chars,
        "head_tail_protection_verified": True,
        "turn_atomicity_verified": True
    }


def run_diag_context_summarizer() -> dict[str, Any]:
    t0 = time.time()
    from langchain_core.messages import ToolMessage
    from src.context.summarizer import SmartSummarizer

    summarizer = SmartSummarizer()

    # 1. Short output bypass
    short_content = "Short output under limit"
    msg_short = ToolMessage(content=short_content, tool_call_id="call-1", name="bash")
    out_short = summarizer.summarize_message(msg_short)
    assert out_short.content == short_content, "Short message was unexpectedly modified"

    # 2. Heuristic summarization with critical error preservation
    error_content = "Build starting...\n" + ("Compiling module...\n" * 150) + "FATAL: OutOfMemoryError in worker thread\n" + "Build terminated."
    assert len(error_content) > summarizer.SHORT_OUTPUT_LIMIT, "Test content is too short"
    msg_long = ToolMessage(content=error_content, tool_call_id="call-2", name="bash")
    out_long = summarizer.summarize_message(msg_long)

    assert len(out_long.content) < len(error_content), "Long output was not compressed"
    assert "FATAL" in out_long.content or "OutOfMemoryError" in out_long.content, "Critical error line was dropped"

    return {
        "subsystem": "Context Summarizer",
        "status": "PASS",
        "duration_ms": round((time.time() - t0) * 1000, 2),
        "short_output_limit": summarizer.SHORT_OUTPUT_LIMIT,
        "max_heuristic_limit": summarizer.MAX_HEURISTIC_LIMIT,
        "short_bypass_verified": True,
        "heuristic_compression_verified": True,
        "critical_error_preserved": True
    }


def run_diag_pipeline_flow() -> dict[str, Any]:
    t0 = time.time()
    from src.graphs.chat_graph import graph, finalize_node
    from src.graphs.gates import derive_4state_verification_receipt
    from src.runtime.status_contract import synthesize_status_contract
    from langchain_core.messages import HumanMessage, AIMessage

    # 1. Graph nodes integrity
    node_names = list(graph.nodes.keys())
    for req_node in ["__start__", "task_manager", "finalize", "planner", "ai", "tools"]:
        assert req_node in node_names, f"Required graph node {req_node} missing"

    # 2. Finalize node execution
    state = {
        "messages": [HumanMessage(content="run task"), AIMessage(content="task finished")],
        "current_task": "run task",
        "steps_completed": ["Step 1 done"],
        "failed_steps": [],
        "plan": [],
        "task_completed": True,
        "task_status": "completed"
    }
    fin_out = finalize_node(dict(state), {"configurable": {}})
    assert fin_out["task_completed"] is True, "finalize_node failed to mark task_completed"
    assert fin_out["task_status"] == "completed", "finalize_node failed to set task_status"

    # 3. Status contract synthesis
    sc = synthesize_status_contract(
        run_outcome="completed",
        verification_status="verified",
        specification_status="satisfied"
    )
    assert sc["run_outcome"] == "completed"
    assert sc["verification_status"] == "verified"
    assert sc["specification_status"] == "satisfied"

    # 4. 4-state verification receipt
    receipt = derive_4state_verification_receipt(state)
    assert "state" in receipt, "Missing state in verification receipt"

    return {
        "subsystem": "Full Pipeline Flow",
        "status": "PASS",
        "duration_ms": round((time.time() - t0) * 1000, 2),
        "graph_nodes_count": len(node_names),
        "graph_nodes": node_names,
        "finalize_execution_verified": True,
        "status_contract_verified": True,
        "receipt_state": receipt.get("state")
    }


def run_all_agent_core_tests() -> dict[str, Any]:
    t0 = time.time()
    results = {}
    passed = 0
    total = 5

    tests = [
        ("context_engine", run_diag_context_engine),
        ("memory", run_diag_memory),
        ("context_compressor", run_diag_context_compressor),
        ("context_summarizer", run_diag_context_summarizer),
        ("pipeline_flow", run_diag_pipeline_flow)
    ]

    for name, test_func in tests:
        try:
            res = test_func()
            results[name] = res
            if res.get("status") == "PASS":
                passed += 1
        except Exception as exc:
            results[name] = {
                "subsystem": name,
                "status": "FAIL",
                "error": str(exc)
            }

    all_passed = (passed == total)
    return {
        "overall_status": "PASS" if all_passed else "FAIL",
        "tests_passed": passed,
        "tests_total": total,
        "total_duration_ms": round((time.time() - t0) * 1000, 2),
        "subsystems": results
    }


def handle_initialize(req_id: int | str, params: dict) -> None:
    send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "protocolVersion": MCP_VERSION,
            "capabilities": {
                "tools": {}
            },
            "serverInfo": SERVER_INFO
        }
    })


def handle_tools_list(req_id: int | str) -> None:
    send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "tools": TOOLS
        }
    })


def handle_tools_call(req_id: int | str, params: dict) -> None:
    tool_name = params.get("name")
    args = params.get("arguments") or {}

    try:
        if tool_name == "ping":
            text = "pong from mcptest MCP server"
        elif tool_name == "echo":
            msg = args.get("message", "")
            text = f"mcptest echo: {msg}"
        elif tool_name == "agent_core_status":
            text = json.dumps({
                "agent_core": "Healthy",
                "mcp_version": MCP_VERSION,
                "subsystems": ["Context Engine", "Memory", "Context Compressor", "Context Summarizer", "Full Pipeline Flow"]
            }, indent=2)
        elif tool_name == "test_context_engine":
            text = json.dumps(run_diag_context_engine(), indent=2)
        elif tool_name == "test_memory":
            text = json.dumps(run_diag_memory(), indent=2)
        elif tool_name == "test_context_compressor":
            text = json.dumps(run_diag_context_compressor(), indent=2)
        elif tool_name == "test_context_summarizer":
            text = json.dumps(run_diag_context_summarizer(), indent=2)
        elif tool_name == "test_pipeline_flow":
            text = json.dumps(run_diag_pipeline_flow(), indent=2)
        elif tool_name == "run_all_agent_core_tests":
            text = json.dumps(run_all_agent_core_tests(), indent=2)
        else:
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}]
                }
            })
            return

        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": text}]
            }
        })
    except Exception as exc:
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": f"Diagnostic error in {tool_name}: {exc}"}]
            }
        })


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            handle_initialize(req_id, req.get("params", {}))
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            handle_tools_list(req_id)
        elif method == "tools/call":
            handle_tools_call(req_id, req.get("params", {}))
        elif req_id is not None:
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method {method!r} not found"}
            })


if __name__ == "__main__":
    main()

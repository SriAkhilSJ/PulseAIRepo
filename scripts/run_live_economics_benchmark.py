"""
Phase 9.3.2.1: Live End-to-End Agent Economics Validation Runner with Corrected Dispatch & Finalization Phase.
Executes 3 paired trials of Task 1 (Code Lookup) and Task 2 (Single-File Bug Correction)
on z-ai/glm-5.3-flash via the Velona Gateway under authorized budget caps:
- Max cumulative spend: ₹2.50 INR
- Max per-task spend: ₹1.50 INR
- Conservative uncached billing on actual provider-returned token usage
- Isolated workspace snapshots per trial
- Argument normalization via normalize_tool_arguments
- Explicit finalization phase (withholding tools on final turn to force plain-text synthesis)
- Non-retryable infrastructure error classification and immediate termination
"""

import sys
sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import os
import time
import json
import uuid
import shutil
import subprocess
from pathlib import Path
import dotenv

dotenv.load_dotenv(".env")

from openai import OpenAI
from src.tools.file_tools import read_file, list_files, search_code, edit_file
from src.graphs.task_validation import validate_database_lookup, validate_single_file_modification
from src.runtime.retry_controller import (
    ToolRetryController,
    ERROR_NON_RETRYABLE_INFRASTRUCTURE,
    ERROR_RETRYABLE,
)
from src.runtime.argument_normalizer import normalize_tool_arguments, NormalizationResult
from src.tools.terminal_tools import run_terminal
from src.context.safety_guard import SafetyGuard

# Canonical Financial Constants
USD_TO_INR_BASE = 86.00
FOREX_SPREAD = 1.005
GATEWAY_FEE = 1.070
USD_TO_INR_EFFECTIVE = USD_TO_INR_BASE * FOREX_SPREAD * GATEWAY_FEE  # 92.4801

# Rate Card: z-ai/glm-5.3-flash on Velona (Conservative: No Cache Discounts Assumed)
RATE_INPUT_UNCACHED = 0.15   # $ / 1M tokens
RATE_OUTPUT = 0.50           # $ / 1M tokens

PILOT_BUDGET_CAP_INR = 2.50
TASK_BUDGET_CAP_INR = 1.50
MAX_TURNS_PER_TASK = 6

BUGGY_CALC_CODE = '''"""Calculator Service with an intentional discount bug for Phase 9.3.2 benchmark."""

def calculate_discounted_total(subtotal: float, discount_percent: float, is_vip: bool = False) -> float:
    """Calculate total after discount. VIP customers receive an additional 5% discount."""
    if subtotal < 0 or discount_percent < 0 or discount_percent > 100:
        raise ValueError("Invalid subtotal or discount percentage")
    total_discount = discount_percent
    if is_vip:
        total_discount += 5.0
    # BUG: Adds discount to subtotal instead of subtracting it!
    return round(subtotal * (1.0 + total_discount / 100.0), 2)
'''

TEST_CALC_CODE = '''import pytest
from calc_service import calculate_discounted_total

def test_standard_discount():
    # 100 with 10% discount should be 90.0
    assert calculate_discounted_total(100.0, 10.0) == 90.0

def test_vip_discount():
    # 100 with 10% discount + 5% VIP bonus should be 85.0
    assert calculate_discounted_total(100.0, 10.0, is_vip=True) == 85.0

def test_zero_discount():
    assert calculate_discounted_total(100.0, 0.0) == 100.0

def test_invalid_input():
    with pytest.raises(ValueError):
        calculate_discounted_total(-10.0, 10.0)
'''

current_trial_dir = None

def setup_isolated_trial_workspace(trial_idx: int) -> str:
    trial_dir = os.path.join("fixtures", "live_benchmark_calc", f"trial_{trial_idx}")
    os.makedirs(trial_dir, exist_ok=True)
    with open(os.path.join(trial_dir, "calc_service.py"), "w", encoding="utf-8") as f:
        f.write(BUGGY_CALC_CODE)
    with open(os.path.join(trial_dir, "test_calc_service.py"), "w", encoding="utf-8") as f:
        f.write(TEST_CALC_CODE)
    return trial_dir

def get_tool_definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files and subdirectories at a given directory path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative directory path (e.g. 'src/config')"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "Search code across repository files using ripgrep keyword match.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Code pattern or keyword to search for"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read file contents with optional start_line and end_line bounds.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative file path to read"},
                        "start_line": {"type": "integer", "description": "1-based starting line number"},
                        "end_line": {"type": "integer", "description": "1-based ending line number"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "Apply a targeted surgical replacement (old_text -> new_text) to an existing file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative file path to edit"},
                        "old_text": {"type": "string", "description": "Exact text block to replace"},
                        "new_text": {"type": "string", "description": "New text block to insert"}
                    },
                    "required": ["path", "old_text", "new_text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_terminal",
                "description": "Run a shell or test command in workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Terminal command (e.g. 'pytest ...')"}
                    },
                    "required": ["command"]
                }
            }
        }
    ]

def dispatch_tool(
    name: str,
    args: dict,
    workspace_root: str = None,
    phase: str = "DISCOVERY",
    session_id: str = None,
    request_id: str = None,
    turn: int = 1,
) -> tuple[str, dict]:
    """
    Executes a tool with strict schema argument normalization, fail-closed workspace security,
    state-machine enforcement, and separate RunnableConfig context.
    Returns: (tool_output_string, normalized_args_dict)
    """
    global current_trial_dir

    # 1. State Machine Check: Reject any tool call during FINALIZATION
    if phase == "FINALIZATION":
        violation_msg = (
            f"⛔ Protocol violation: Tool call '{name}' rejected at dispatcher level. "
            "The agent runtime has entered the FINALIZATION phase. "
            "No further tool invocations, filesystem access, or terminal operations are permitted."
        )
        return violation_msg, args

    # 2. Fail-Closed Workspace Check
    if workspace_root is None or not str(workspace_root).strip():
        return (
            "⛔ Tool execution refused: missing workspace restriction. "
            "The benchmark dispatcher requires an explicit, non-empty workspace_root.",
            args,
        )

    resolved_ws = str(Path(workspace_root).resolve())
    if not os.path.exists(resolved_ws) or not os.path.isdir(resolved_ws):
        return (
            f"⛔ Tool execution refused: authorized workspace directory does not exist or is not a directory: {resolved_ws}",
            args,
        )

    cfg = {"configurable": {"workspace": resolved_ws, "thread_id": session_id or "live-bench"}}

    # 3. Argument Normalization
    norm_res = normalize_tool_arguments(name, args)
    if norm_res.status == "rejected":
        return f"❌ Argument normalization error: {norm_res.error}", args

    norm_args = norm_res.normalized_args

    # 4. Mandatory Fail-Closed SafetyGuard Approval Inspection
    try:
        guard = SafetyGuard(resolved_ws)
    except Exception as e:
        exc_cls = type(e).__name__
        return (
            f"⛔ NON-RETRYABLE INFRASTRUCTURE ERROR: SafetyGuard initialization failure ({exc_cls}) "
            f"for workspace '{resolved_ws}': {e}",
            norm_args,
        )

    try:
        check_res = guard.check_tool_call(name, norm_args)
    except Exception as e:
        exc_cls = type(e).__name__
        return (
            f"⛔ NON-RETRYABLE INFRASTRUCTURE ERROR: SafetyGuard inspection failure ({exc_cls}) "
            f"for tool '{name}': {e}",
            norm_args,
        )

    if not isinstance(check_res, tuple) or len(check_res) != 2 or not isinstance(check_res[0], bool):
        return (
            f"⛔ NON-RETRYABLE INFRASTRUCTURE ERROR: Invalid safety inspection result from SafetyGuard "
            f"for tool '{name}' (expected tuple[bool, str], got {check_res!r})",
            norm_args,
        )

    is_safe, warning = check_res
    if not is_safe:
        return (
            f"⛔ Security denial: Safety approval refused for tool '{name}': {warning}",
            norm_args,
        )

    try:
        if name == "list_files":
            p = norm_args.get("path", ".")
            out = str(list_files.invoke({"path": p}, config=cfg))
            return out, norm_args
        elif name == "search_code":
            q = norm_args.get("query", "")
            out = str(search_code.invoke({"query": q}, config=cfg))
            return out, norm_args
        elif name == "read_file":
            p = norm_args.get("path", "")
            if current_trial_dir and (p.startswith(current_trial_dir.replace("\\", "/")) or p.startswith(current_trial_dir)):
                p = os.path.relpath(p, current_trial_dir).replace("\\", "/")
            kwargs = {"path": p}
            if "start_line" in norm_args and norm_args["start_line"] is not None:
                kwargs["start_line"] = int(norm_args["start_line"])
            if "end_line" in norm_args and norm_args["end_line"] is not None:
                kwargs["end_line"] = int(norm_args["end_line"])
            out = str(read_file.invoke(kwargs, config=cfg))
            return out, norm_args
        elif name == "edit_file":
            p = norm_args.get("path", "")
            if current_trial_dir and (p.startswith(current_trial_dir.replace("\\", "/")) or p.startswith(current_trial_dir)):
                p = os.path.relpath(p, current_trial_dir).replace("\\", "/")
            old_t = norm_args.get("old_text", "")
            new_t = norm_args.get("new_text", "")
            out = str(edit_file.invoke({"path": p, "old_text": old_t, "new_text": new_t}, config=cfg))
            return out, norm_args
        elif name in ("run_terminal", "terminal"):
            cmd = norm_args.get("command", "")
            # Workspace boundary check: Prevent explicit directory traversal escape
            if any(esc in cmd for esc in ("../..", "..\\..")):
                return "⛔ Tool execution refused: command attempts to escape authorized workspace.", norm_args
            # Dispatch through the production run_terminal implementation
            out = str(run_terminal.invoke({"command": cmd}, config=cfg))
            return out, norm_args
        else:
            return f"Error: Unknown tool {name}", norm_args
    except Exception as e:
        exc_cls = type(e).__name__
        return f"Tool execution error ({exc_cls}): {e}", norm_args


def get_git_dirty_set() -> set[str]:
    res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    lines = res.stdout.strip().splitlines()
    return {l[3:].strip() for l in lines if l.strip()}

def run_agent_task(
    client: OpenAI,
    task_id: str,
    prompt: str,
    trial_idx: int,
    tools: list,
    workspace_root: str,
) -> dict:
    session_id = f"live-trial-{trial_idx}-{task_id[:12]}-{uuid.uuid4().hex[:6]}"
    git_before = get_git_dirty_set()
    
    system_prompt = (
        "You are CrusorAI, an expert coding agent. Use available tools to fulfill user instructions. "
        "Be direct, surgical, and minimal. Do not modify files unnecessarily. "
        "CRITICAL INSTRUCTION: When you have gathered the required evidence or verified your code edit with pytest, "
        "conclude immediately by formulating your final answer in plain markdown."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    turn_telemetry = []
    total_task_usd = 0.0
    total_task_inr = 0.0
    final_response_text = ""
    retry_ctrl = ToolRetryController(max_consecutive_identical_failures=1)
    
    phase = "DISCOVERY"
    
    for turn in range(1, MAX_TURNS_PER_TASK + 1):
        # Finalization enforcement: on turn 6 (or if phase is FINALIZATION), withhold tool definitions
        active_tools = tools if phase != "FINALIZATION" and turn < MAX_TURNS_PER_TASK else None
        
        t0 = time.time()
        try:
            kwargs = {
                "model": "z-ai/glm-5.3-flash",
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.1,
            }
            if active_tools:
                kwargs["tools"] = active_tools
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            turn_telemetry.append({
                "turn": turn,
                "error": str(e),
                "latency_ms": latency_ms,
                "cost_usd": 0.0,
                "cost_inr": 0.0
            })
            break
            
        latency_ms = int((time.time() - t0) * 1000)
        choice = resp.choices[0]
        msg = choice.message
        
        usage = resp.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0
        
        pt_details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = getattr(pt_details, "cached_tokens", 0) or 0
        cache_write_tokens = getattr(pt_details, "cache_write_tokens", None)
        
        # Conservative billing (Rate Card A):
        turn_cost_usd = (prompt_tokens / 1e6) * RATE_INPUT_UNCACHED + (completion_tokens / 1e6) * RATE_OUTPUT
        turn_cost_inr = turn_cost_usd * USD_TO_INR_EFFECTIVE
        
        total_task_usd += turn_cost_usd
        total_task_inr += turn_cost_inr
        
        record = {
            "session_id": session_id,
            "task_id": task_id,
            "trial_index": trial_idx,
            "turn_number": turn,
            "requested_model": "z-ai/glm-5.3-flash",
            "returned_model": resp.model,
            "provider_request_id": resp.id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cached_tokens": cached_tokens,
            "cache_write_tokens": cache_write_tokens,
            "reasoning_tokens": 0,
            "retry_calls": 0,
            "auxiliary_calls": 0,
            "subagent_calls": 0,
            "latency_ms": latency_ms,
            "cost_usd": turn_cost_usd,
            "cost_inr": turn_cost_inr,
            "billing_classification": "LIVE_PROVIDER_TELEMETRY (Conservative Uncached Rate)",
        }
        turn_telemetry.append(record)
        
        # Safety circuit breaker
        if total_task_inr > TASK_BUDGET_CAP_INR:
            print(f"  [CIRCUIT BREAKER] Task {task_id} reached task budget cap (₹{total_task_inr:.4f}). Halting.")
            break
            
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            # Model finished with text response
            final_response_text = msg.content or ""
            break
            
        if msg.content:
            final_response_text = msg.content
            
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in tool_calls
            ]
        })
        
        has_fatal_infra_error = False
        
        for tc in tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except Exception:
                fn_args = {}
                
            abort_dup, abort_reason = retry_ctrl.should_abort_duplicate(fn_name, fn_args)
            if abort_dup:
                tool_output = f"⛔ {abort_reason}"
                status = "error"
            else:
                tool_output, norm_args = dispatch_tool(
                    name=fn_name,
                    args=fn_args,
                    workspace_root=workspace_root,
                    phase=phase,
                    session_id=session_id,
                    request_id=resp.id,
                    turn=turn,
                )
                if "Protocol violation" in tool_output:
                    status = "protocol_violation"
                elif "Security denial" in tool_output:
                    status = "security_denial"
                elif "SafetyGuard" in tool_output:
                    status = "security_inspection_failure"
                elif any(w in tool_output for w in ("⛔", "❌", "Error:", "error", "Tool execution error")):
                    status = "error"
                else:
                    status = "success"
                
                denial_status = (
                    "DENIED_SECURITY_POLICY" if status == "security_denial"
                    else "DENIED_INSPECTION_FAILURE" if status == "security_inspection_failure"
                    else None
                )

                # Check for fatal non-retryable infrastructure / security errors
                is_fatal, fatal_msg = retry_ctrl.check_infrastructure_error(
                    tool_name=fn_name,
                    error_msg=tool_output,
                    request_id=resp.id,
                    session_id=session_id,
                    workspace=workspace_root,
                    security_denial_status=denial_status,
                )
                if is_fatal:
                    tool_output = fatal_msg
                    has_fatal_infra_error = True
                    
                retry_ctrl.record_attempt(
                    turn=turn,
                    tool_name=fn_name,
                    args=fn_args,
                    status=status,
                    error=tool_output if status != "success" else None,
                    request_id=resp.id,
                    session_id=session_id,
                    workspace=workspace_root,
                    security_denial_status=denial_status,
                )
                
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_output
            })
            
            # Check for transition into FINALIZATION phase
            if fn_name in ("run_terminal", "terminal") and "passed" in tool_output.lower() and "failed" not in tool_output.lower():
                phase = "FINALIZATION"
                messages.append({
                    "role": "user",
                    "content": "Pytest passed successfully! Conclude now with your final markdown response explaining the fix. Do not make any further tool calls."
                })
            elif fn_name in ("search_code", "read_file") and any(k in tool_output.lower() for k in ("database_url", "create_engine", "sqlite3.connect")):
                phase = "FINALIZATION"
                messages.append({
                    "role": "user",
                    "content": "You have located the required database configuration and connection parameters. Conclude now with your complete final response answering all prompt questions. Do not make any further tool calls."
                })
                
        if has_fatal_infra_error:
            print(f"  [FATAL INFRASTRUCTURE HALT] Terminating session due to unrecoverable tool defect: {retry_ctrl.break_reason}")
            final_response_text = f"Session aborted: {retry_ctrl.break_reason}"
            break
            
        # When entering final turn, remind model to finalize
        if turn == MAX_TURNS_PER_TASK - 1:
            phase = "FINALIZATION"
            messages.append({
                "role": "user",
                "content": "You have reached the final turn. Provide your complete final answer now in plain markdown. Tools are disabled for the final turn."
            })
                
    git_after = get_git_dirty_set()
    newly_modified = git_after - git_before
    
    return {
        "session_id": session_id,
        "task_id": task_id,
        "trial_index": trial_idx,
        "turns_count": len(turn_telemetry),
        "total_task_usd": total_task_usd,
        "total_task_inr": total_task_inr,
        "final_response": final_response_text,
        "turn_telemetry": turn_telemetry,
        "newly_modified_files": list(newly_modified)
    }

def verify_task_1(session_result: dict) -> tuple[bool, str]:
    res = validate_database_lookup(
        final_response=session_result.get("final_response", ""),
        modified_files=session_result.get("newly_modified_files", []),
    )
    reason = f"Passed: {res.passed} (path={res.has_exact_file_path}, url={res.has_url_resolution}, engine={res.has_engine_instantiation}, reasons={res.failure_reasons})"
    return res.passed, reason

def verify_task_2(session_result: dict, trial_dir: str) -> tuple[bool, str]:
    res = validate_single_file_modification(
        trial_dir=trial_dir,
        target_rel_path="calc_service.py",
        test_rel_path="test_calc_service.py",
        modified_files=session_result.get("newly_modified_files", []),
        expected_patch_pattern=r"return\s+round\(\s*subtotal\s*\*\s*\(\s*1\.0\s*-\s*total_discount",
    )
    reason = f"Passed: {res.passed} (test_passed={res.tests_passed}, fix_verified={res.fix_verified_in_source}, clean={res.git_diff_clean}, reasons={res.failure_reasons})"
    return res.passed, reason

def run_paired_benchmark(num_pairs: int = 3):
    client = OpenAI(
        base_url=os.environ.get("CUSTOM_BASE_URL", "https://velona.in/v1"),
        api_key=os.environ.get("CUSTOM_API_KEY"),
        timeout=45.0,
    )
    tools = get_tool_definitions()
    
    task_1_prompt = (
        "Locate where the database configuration and connection parameters are defined in this repository. "
        "Return the exact file path and explain how the database URL is resolved and how the connection engine is instantiated. "
        "Do not modify any files."
    )
    
    all_sessions = []
    cumulative_spend_inr = 0.0
    
    print(f"================================================================================")
    print(f"  CRUSOR AI IDE — PHASE 9.3.2.2 LIVE BENCHMARK EXECUTION")
    print(f"  Model: z-ai/glm-5.3-flash via Velona Gateway")
    print(f"  Cumulative Budget Cap: ₹{PILOT_BUDGET_CAP_INR:.2f} INR | Per-Task Cap: ₹{TASK_BUDGET_CAP_INR:.2f} INR")
    print(f"  Target Ceiling: ₹5.00 INR per simple coding task")
    print(f"================================================================================\n")
    
    for pair in range(1, num_pairs + 1):
        print(f">>> STARTING PAIRED TRIAL {pair} / {num_pairs} <<<")
        
        # 1. Run Task 1 (Repository Code Lookup)
        global current_trial_dir
        current_trial_dir = None
        repo_ws = str(Path(".").resolve())
        print(f"  [Trial {pair} - Task 1] Repository Code Lookup (Workspace: {repo_ws})...")
        t1_res = run_agent_task(client, "task-1-code-lookup", task_1_prompt, pair, tools, workspace_root=repo_ws)
        t1_pass, t1_reason = verify_task_1(t1_res)
        t1_res["verification_passed"] = t1_pass
        t1_res["verification_reason"] = t1_reason
        cumulative_spend_inr += t1_res["total_task_inr"]
        print(f"    Turns: {t1_res['turns_count']} | Spend: ₹{t1_res['total_task_inr']:.4f} INR | Verified: {t1_pass} ({t1_reason})")
        print(f"    Cumulative Spend: ₹{cumulative_spend_inr:.4f} INR / ₹{PILOT_BUDGET_CAP_INR:.2f} Cap\n")
        all_sessions.append(t1_res)
        
        if cumulative_spend_inr >= PILOT_BUDGET_CAP_INR:
            print("  [BUDGET CEILING HALT] Cumulative cap reached. Stopping immediately.")
            break
            
        # 2. Setup Clean Isolated Snapshot & Run Task 2 (Bug Correction)
        trial_dir = setup_isolated_trial_workspace(pair)
        current_trial_dir = trial_dir
        trial_ws = str(Path(trial_dir).resolve())
        
        task_2_prompt = (
            "Inspect the designated calculation module at calc_service.py and identify the edge-case discount calculation defect. "
            "First reproduce the defect using the provided pytest test at test_calc_service.py via run_terminal. "
            "Apply a surgical correction to calc_service.py using edit_file, rerun test_calc_service.py using run_terminal to verify all tests pass, "
            "and verify that the Git diff contains only the intended modification."
        )
        
        print(f"  [Trial {pair} - Task 2] Single-File Bug Correction (Workspace: {trial_ws})...")
        t2_res = run_agent_task(client, "task-2-bug-correction", task_2_prompt, pair, tools, workspace_root=trial_ws)
        t2_pass, t2_reason = verify_task_2(t2_res, trial_dir)
        t2_res["verification_passed"] = t2_pass
        t2_res["verification_reason"] = t2_reason
        cumulative_spend_inr += t2_res["total_task_inr"]
        print(f"    Turns: {t2_res['turns_count']} | Spend: ₹{t2_res['total_task_inr']:.4f} INR | Verified: {t2_pass} ({t2_reason})")
        print(f"    Cumulative Spend: ₹{cumulative_spend_inr:.4f} INR / ₹{PILOT_BUDGET_CAP_INR:.2f} Cap\n")
        all_sessions.append(t2_res)
        
        if cumulative_spend_inr >= PILOT_BUDGET_CAP_INR:
            print("  [BUDGET CEILING HALT] Cumulative cap reached. Stopping immediately.")
            break
            
    # Save master ledger
    with open("live_economics_ledger_phase932.json", "w", encoding="utf-8") as f:
        json.dump(all_sessions, f, indent=2)
        
    print(f"================================================================================")
    print(f"  BENCHMARK COMPLETE: {len(all_sessions)} sessions executed across {num_pairs} paired trials.")
    print(f"  Total Cumulative API Expenditure: ₹{cumulative_spend_inr:.4f} INR (Cap: ₹{PILOT_BUDGET_CAP_INR:.2f})")
    print(f"================================================================================\n")
    return all_sessions

if __name__ == "__main__":
    run_paired_benchmark(num_pairs=3)

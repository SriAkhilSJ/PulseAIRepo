import sys
sys.path.insert(0, ".")
import time
import copy
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.context.compaction import (
    transform_completed_tool_receipts,
    compact_assistant_tool_call_arguments,
)
from src.context.token_budget import count_tokens

def generate_session(rounds: int):
    msgs = [HumanMessage(content=f"Initial request for {rounds} round simulation")]
    for r in range(1, rounds + 1):
        cid = f"call_{r:04d}"
        if r % 5 == 0:
            # A test run
            cmd = f"pytest tests/test_module_{r}.py"
            out = f"=== 10 passed in 0.5s ===\nExit code: 0"
        elif r % 7 == 0:
            # File read
            cmd = "read_file"
            out = f"# Module {r} code\ndef func_{r}():\n    return {r}\n" * 10
        elif r % 11 == 0:
            # File write
            cmd = "write_file"
            out = "File written successfully"
        else:
            cmd = f"python -m scripts.run_{r} --flag"
            out = f"Processed batch {r}\nAll items valid\nExit code: 0"
            
        if cmd == "read_file":
            ai_msg = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": f"src/mod_{r}.py"}, "id": cid}])
            tool_msg = ToolMessage(content=out, tool_call_id=cid, name="read_file")
        elif cmd == "write_file":
            ai_msg = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": f"src/mod_{r}.py", "content": out * 5}, "id": cid}])
            tool_msg = ToolMessage(content="File saved", tool_call_id=cid, name="write_file")
        else:
            ai_msg = AIMessage(content="", tool_calls=[{"name": "run_terminal", "args": {"command": cmd}, "id": cid}])
            tool_msg = ToolMessage(content=out, tool_call_id=cid, name="run_terminal")
            
        ai_resp = AIMessage(content=f"Completed step {r}.")
        msgs.extend([ai_msg, tool_msg, ai_resp])
    return msgs

model = "claude-3-5-sonnet-20241022"

print("=" * 80)
print("STAGE 7: IDEMPOTENCY AND LONG-SESSION STABILITY VALIDATION")
print("=" * 80)

for rounds in [10, 25, 50, 100]:
    msgs = generate_session(rounds)
    orig_tokens = count_tokens(msgs, model)
    msg_count = len(msgs)
    
    # Pass 1
    t0 = time.perf_counter()
    p1 = compact_assistant_tool_call_arguments(copy.deepcopy(msgs), keep_recent=3)
    p1 = transform_completed_tool_receipts(p1, keep_recent=3)
    t1 = time.perf_counter()
    pass1_ms = (t1 - t0) * 1000.0
    p1_tokens = count_tokens(p1, model)
    
    # Pass 2 (Idempotency check)
    t0 = time.perf_counter()
    p2 = compact_assistant_tool_call_arguments(copy.deepcopy(p1), keep_recent=3)
    p2 = transform_completed_tool_receipts(p2, keep_recent=3)
    t1 = time.perf_counter()
    pass2_ms = (t1 - t0) * 1000.0
    p2_tokens = count_tokens(p2, model)
    
    # Pass 3
    p3 = compact_assistant_tool_call_arguments(copy.deepcopy(p2), keep_recent=3)
    p3 = transform_completed_tool_receipts(p3, keep_recent=3)
    p3_tokens = count_tokens(p3, model)
    
    # Verify strict message content identity between Pass 1 and Pass 2
    idempotent = True
    if len(p1) != len(p2):
        idempotent = False
    else:
        for m1, m2 in zip(p1, p2):
            if type(m1) is not type(m2) or m1.content != m2.content:
                idempotent = False
                break
                
    savings = (orig_tokens - p1_tokens) / orig_tokens * 100.0
    print(f"Rounds: {rounds:3d} ({msg_count:3d} msgs) | Orig: {orig_tokens:6d} tok | Compacted: {p1_tokens:6d} tok (-{savings:.1f}%) | "
          f"P1: {pass1_ms:.2f}ms | P2: {pass2_ms:.2f}ms | Idempotent: {idempotent} (P1==P2: {p1_tokens == p2_tokens == p3_tokens})")


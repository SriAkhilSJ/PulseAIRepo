import sys
sys.path.insert(0, ".")
from scripts.benchmark_eager_compaction import _build_trace
from src.context.compaction import transform_completed_tool_receipts, compact_assistant_tool_call_arguments
from src.context.token_budget import count_tokens
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

model = "claude-3-5-sonnet-20241022"
scenarios = [
    "simple_lookup",
    "single_file_edit",
    "multi_file_feature",
    "debugging",
    "test_generation",
    "complex_repo_task",
]

total_compacted = 0
total_receipts = 0
total_verbatim_tools = 0
total_unresolved = 0

total_system = 0
total_human = 0
total_ai = 0

for s in scenarios:
    trace = _build_trace(s)
    comp = transform_completed_tool_receipts(trace, keep_recent=3)
    comp = compact_assistant_tool_call_arguments(comp, keep_recent=3)
    
    c_tot = count_tokens(comp, model)
    total_compacted += c_tot
    
    r_msgs = [m for m in comp if isinstance(m, ToolMessage) and m.content.startswith("[")]
    v_msgs = [m for m in comp if isinstance(m, ToolMessage) and not m.content.startswith("[")]
    u_msgs = [m for m in comp if isinstance(m, ToolMessage) and "Traceback" in m.content]
    
    sys_msgs = [m for m in comp if isinstance(m, SystemMessage)]
    h_msgs = [m for m in comp if isinstance(m, HumanMessage)]
    ai_msgs = [m for m in comp if isinstance(m, AIMessage)]
    
    total_receipts += count_tokens(r_msgs, model) if r_msgs else 0
    total_verbatim_tools += count_tokens(v_msgs, model) if v_msgs else 0
    total_unresolved += count_tokens(u_msgs, model) if u_msgs else 0
    
    total_system += count_tokens(sys_msgs, model) if sys_msgs else 0
    total_human += count_tokens(h_msgs, model) if h_msgs else 0
    total_ai += count_tokens(ai_msgs, model) if ai_msgs else 0

print(f"Total Compacted Tokens: {total_compacted}")
print(f"  Tool Receipts:        {total_receipts}")
print(f"  Verbatim Tools:       {total_verbatim_tools}")
print(f"  Unresolved Tools:     {total_unresolved} (sub-category of verbatim)")
tool_total = total_receipts + total_verbatim_tools
print(f"  Sum of Tool Messages: {tool_total}")
print(f"\nOther Retained Messages (Non-Tool):")
print(f"  System Instructions:  {total_system}")
print(f"  Human User Requests:  {total_human}")
print(f"  Assistant Responses & Tool Calls: {total_ai}")
non_tool_total = total_system + total_human + total_ai
print(f"  Sum of Non-Tool Messages: {non_tool_total}")
print(f"\nReconciled Total: {tool_total} (Tools) + {non_tool_total} (Non-Tools) = {tool_total + non_tool_total}")
print(f"Difference from Compacted Total: {total_compacted - (tool_total + non_tool_total)}")


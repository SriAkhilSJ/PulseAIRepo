# CRUSOR AI IDE — PHASE 9.6: OBSERVABILITY ARCHITECTURE DOCUMENTATION

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.5  
**Implementation Source:** `src/observability/tracing.py`  
**Verdict:** `DESKTOP PERFORMANCE AND OBSERVABILITY VERIFIED`  

---

## 1. OBSERVABILITY TAXONOMY

Each operation across the desktop lifecycle emits structured trace spans conforming to the standard Crusor Observability Schema:

```json
{
  "trace_id": "tr_4a8b9c1d2e3f",
  "span_id": "sp_7f8e9d0a",
  "parent_span_id": "sp_1b2c3d4e",
  "correlation_id": "crusor_1730700000_abc123",
  "component": "python_sidecar",
  "operation": "bridge.decode_frame",
  "start_time": 1730700000.123,
  "end_time": 1730700000.126,
  "duration_ms": 3.125,
  "outcome": "SUCCESS",
  "error_category": null,
  "error_message": null,
  "retry_count": 0,
  "metadata": {
    "frame_type": "prompt",
    "session_id": "sess_default"
  }
}
```

---

## 2. CROSS-TIER COMPONENT PROPAGATION

```
1. Electron Main:     [ span: user_menu_action ] (correlation_id: crusor_1730700000_abc)
                            |
2. Renderer:          [ span: chat_view_submit ] (parent: user_menu_action)
                            |
3. Utility Process:   [ span: ipc_forward_frame ] (parent: chat_view_submit)
                            |
4. Python Sidecar:    [ span: bridge_dispatch_turn ] (parent: ipc_forward_frame)
                            |
5. Agent Core:        [ span: langgraph_step_planning ] (parent: bridge_dispatch_turn)
                            |
6. MCP / Browser:     [ span: mcp_tool_execute ] (parent: langgraph_step_planning)
```

Developers can trace any slow or failed user interaction end-to-end across all 6 architectural tiers using a single `correlation_id`.

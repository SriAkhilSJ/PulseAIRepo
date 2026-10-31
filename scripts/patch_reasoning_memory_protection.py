with open('PulseAIRepo/scripts/run_bridge_turn.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = '''                if ftype in ("reasoning", "reasoning.update"):
                    delta = str(frame.get("text") or frame.get("delta") or frame.get("content") or "")
                    if delta:
                        accumulated_reasoning.append(delta)

                if ftype in EPHEMERAL_CHUNK_TYPES and not raw_stream_chunks:
                    pass
                else:
                    if ftype == "llm.response" and accumulated_reasoning:
                        full_thought = "".join(accumulated_reasoning)
                        if full_thought and not frame.get("reasoning"):
                            frame["reasoning"] = full_thought
                        accumulated_reasoning.clear()'''

replacement = '''                if ftype in ("reasoning", "reasoning.update"):
                    delta = str(frame.get("text") or frame.get("delta") or frame.get("content") or "")
                    if delta and len(accumulated_reasoning) < 500:
                        accumulated_reasoning.append(delta)

                if ftype in EPHEMERAL_CHUNK_TYPES and not raw_stream_chunks:
                    pass
                else:
                    if ftype == "llm.response" and accumulated_reasoning:
                        try:
                            full_thought = "".join(accumulated_reasoning)
                            if full_thought and not frame.get("reasoning"):
                                frame["reasoning"] = full_thought
                        except MemoryError:
                            frame["reasoning"] = "[reasoning truncated]"
                        accumulated_reasoning.clear()'''

if target in text:
    text = text.replace(target, replacement, 1)
    with open('PulseAIRepo/scripts/run_bridge_turn.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("PATCH APPLIED: Protected accumulated_reasoning against MemoryError")
else:
    print("TARGET NOT FOUND in run_bridge_turn.py")

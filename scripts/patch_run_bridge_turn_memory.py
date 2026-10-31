with open('PulseAIRepo/scripts/run_bridge_turn.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = '''                    if ftype == "llm.response" and accumulated_reasoning:
                        full_thought = "".join(accumulated_reasoning)
                        if full_thought and not frame.get("reasoning"):
                            frame["reasoning"] = full_thought
                        accumulated_reasoning.clear()
                    out.write(json.dumps(frame, ensure_ascii=False) + "\\n")
                    out.flush()'''

replacement = '''                    if ftype == "llm.response" and accumulated_reasoning:
                        full_thought = "".join(accumulated_reasoning)
                        if full_thought and not frame.get("reasoning"):
                            frame["reasoning"] = full_thought
                        accumulated_reasoning.clear()
                    try:
                        out.write(json.dumps(frame, ensure_ascii=False) + "\\n")
                    except MemoryError:
                        if "reasoning" in frame and isinstance(frame["reasoning"], str) and len(frame["reasoning"]) > 10000:
                            frame["reasoning"] = frame["reasoning"][:5000] + "\\n...[truncated reasoning]...\\n" + frame["reasoning"][-5000:]
                        out.write(json.dumps(frame, ensure_ascii=False) + "\\n")
                    out.flush()'''

if target in text:
    text = text.replace(target, replacement, 1)
    with open('PulseAIRepo/scripts/run_bridge_turn.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("PATCH APPLIED SUCCESSFULLY to run_bridge_turn.py")
else:
    print("TARGET NOT FOUND in run_bridge_turn.py")

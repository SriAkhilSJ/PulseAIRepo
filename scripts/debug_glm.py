import json
import os
import dotenv
from openai import OpenAI

dotenv.load_dotenv('PulseAIRepo/.env')
client = OpenAI(
    api_key=os.environ['CUSTOM_API_KEY'],
    base_url=os.environ['CUSTOM_BASE_URL'],
    timeout=30.0,
)

frame = None
with open('PulseAIRepo/bench-results/glm_5_3_flash_logpulse_run_1/frames.jsonl', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('type') == 'llm.request' and 'request_payload' in data:
            frame = data
            break

payload = frame['request_payload']
messages = payload['messages']
tools = payload.get('tools')

print(f"System prompt length: {len(messages[0]['content'])} chars", flush=True)
print(f"User prompt length: {len(messages[1]['content'])} chars", flush=True)

# Test A: Small system prompt + small user prompt + tools
try:
    r = client.chat.completions.create(
        model='z-ai/glm-5.3-flash',
        messages=[
            {'role': 'system', 'content': 'You are a coding assistant.'},
            {'role': 'user', 'content': 'Create a file hello.txt containing hello'}
        ],
        tools=tools,
        max_tokens=500,
        stream=False
    )
    print("Test A (Small prompt + tools): SUCCESS ->", r.choices[0].message.tool_calls, flush=True)
except Exception as e:
    print("Test A (Small prompt + tools): FAILED ->", e, flush=True)

# Test B: Full system prompt + user prompt + tools (same as bridge)
try:
    r = client.chat.completions.create(
        model='z-ai/glm-5.3-flash',
        messages=messages,
        tools=tools,
        max_tokens=4096,
        stream=True
    )
    first = next(r)
    print("Test B (Full prompt + tools, stream=True): SUCCESS ->", first, flush=True)
except Exception as e:
    print("Test B (Full prompt + tools, stream=True): FAILED ->", e, flush=True)

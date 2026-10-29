import os, time, dotenv
from openai import OpenAI

dotenv.load_dotenv('PulseAIRepo/.env')
client = OpenAI(
    api_key=os.environ['CUSTOM_API_KEY'],
    base_url=os.environ['CUSTOM_BASE_URL'],
    timeout=60.0,
)

with open('PulseAIRepo/benchmark_logpulse_task.txt', encoding='utf-8') as f:
    prompt = f.read()

print("Testing z-ai/glm-5.3-flash with stream=False...", flush=True)
t0 = time.time()
try:
    resp = client.chat.completions.create(
        model='z-ai/glm-5.3-flash',
        messages=[
            {'role': 'system', 'content': 'You are Crusor Agent.'},
            {'role': 'user', 'content': prompt}
        ],
        stream=False,
        max_tokens=4096
    )
    print(f"stream=False SUCCESS in {time.time()-t0:.2f}s! Tokens: {resp.usage.total_tokens}", flush=True)
    print(f"Content preview: {resp.choices[0].message.content[:150]}", flush=True)
except Exception as e:
    print(f"stream=False FAILED in {time.time()-t0:.2f}s: {e}", flush=True)

print("\nTesting z-ai/glm-5.3-flash with stream=True...", flush=True)
t0 = time.time()
try:
    resp = client.chat.completions.create(
        model='z-ai/glm-5.3-flash',
        messages=[
            {'role': 'system', 'content': 'You are Crusor Agent.'},
            {'role': 'user', 'content': prompt}
        ],
        stream=True,
        max_tokens=4096
    )
    chunks = 0
    chars = 0
    for chunk in resp:
        chunks += 1
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            chars += len(delta.content)
    print(f"stream=True SUCCESS in {time.time()-t0:.2f}s! Chunks: {chunks}, chars: {chars}", flush=True)
except Exception as e:
    print(f"stream=True FAILED in {time.time()-t0:.2f}s: {e}", flush=True)

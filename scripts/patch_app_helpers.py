with open('PulseAIRepo/showcase/agent_ecommerce/app.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = "# ---------------------------------------------------------------------------\n# Catalog"

helpers = """def ok(data, status: int = 200):
    return status, "application/json", json.dumps(data).encode("utf-8")

def error(status: int, message: str, **extra):
    payload = {"error": message, **extra}
    return status, "application/json", json.dumps(payload).encode("utf-8")

# ---------------------------------------------------------------------------
# Catalog"""

if target in text:
    text = text.replace(target, helpers, 1)
    with open('PulseAIRepo/showcase/agent_ecommerce/app.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("SUCCESS: Added ok and error helpers to app.py")
else:
    print("FAILED: Target not found")

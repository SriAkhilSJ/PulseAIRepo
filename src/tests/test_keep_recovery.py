from pathlib import Path

from src.graphs.chat_graph import invoke_agent
from src.config.settings import LLM_PROVIDER, LLM_MODEL


TARGET = Path("generated/keep_recovery_test.py")
THREAD_ID = "keep-recovery-regression"


# Deliberately create a recoverable runtime bug.
TARGET.parent.mkdir(
    parents=True,
    exist_ok=True,
)

TARGET.write_text(
    (
        "x = 10\n"
        "y = 0\n"
        "print(x / y)\n"
    ),
    encoding="utf-8",
)


print("\n=== BEFORE RECOVERY ===")
print(TARGET.read_text(encoding="utf-8"))


print("\n=== RUN AGENT ===")

response = invoke_agent(
    message=(
        "Run generated/keep_recovery_test.py. "
        "Fix the runtime failure without changing "
        "the overall approach, run it again, and verify."
    ),
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="agent",
)

print(response)


print("\n=== VERIFY FILE ===")

assert TARGET.exists(), (
    "Recovery test file disappeared."
)

content = TARGET.read_text(
    encoding="utf-8",
)

print(content)


print("\n=== VERIFY EXECUTION ===")

# Verify independently instead of trusting the LLM response.
import subprocess
import sys


result = subprocess.run(
    [
        sys.executable,
        str(TARGET),
    ],
    capture_output=True,
    text=True,
)

print("Exit code:", result.returncode)
print("stdout:", result.stdout.strip())
print("stderr:", result.stderr.strip())


assert result.returncode == 0, (
    "Recovered program still fails."
)

assert result.stdout.strip(), (
    "Recovered program produced no output."
)


print("\nKEEP RECOVERY TEST PASSED")
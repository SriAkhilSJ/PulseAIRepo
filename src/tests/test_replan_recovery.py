from src.graphs.chat_graph import stream_agent
from pathlib import Path
import subprocess
import sys

from src.graphs.chat_graph import invoke_agent
from src.config.settings import LLM_PROVIDER, LLM_MODEL


SCRIPT = Path("generated/replan_recovery_test.py")
SOURCE = Path("generated/replan_local_source.txt")
OUTPUT = Path("generated/replan_recovery_output.txt")

THREAD_ID = "replan-recovery-regression"


# Start clean.
for path in (SCRIPT, SOURCE, OUTPUT):
    if path.exists():
        path.unlink()


SOURCE.parent.mkdir(
    parents=True,
    exist_ok=True,
)

# This is the alternative source that IS available.
SOURCE.write_text(
    "REPLAN RECOVERY WORKS",
    encoding="utf-8",
)


# The initial strategy deliberately depends on an
# unavailable source.
SCRIPT.write_text(
    (
        "from pathlib import Path\n\n"
        'source = Path("generated/'
        'definitely_missing_remote_data.txt")\n'
        'output = Path("generated/'
        'replan_recovery_output.txt")\n\n'
        "if not source.exists():\n"
        '    raise RuntimeError(\n'
        '        "Required remote data source is permanently unavailable. "\n'
        '        "Use generated/replan_local_source.txt instead."\n'
        "    )\n\n"
        "data = source.read_text(encoding='utf-8')\n"
        "output.write_text(data, encoding='utf-8')\n"
    ),
    encoding="utf-8",
)


print("\n=== BEFORE REPLAN ===")

initial = subprocess.run(
    [
        sys.executable,
        str(SCRIPT),
    ],
    capture_output=True,
    text=True,
)

print("Exit code:", initial.returncode)
print("stderr:", initial.stderr.strip())

assert initial.returncode != 0, (
    "Initial strategy unexpectedly succeeded."
)


print("\n=== RUN AGENT ===")

response = stream_agent(
    message=(
        "Run generated/replan_recovery_test.py and make it work. "
        "The required original data source is permanently unavailable. "
        "If the current strategy cannot work, change approach using "
        "the available local source. Run and verify the result."
    ),
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="agent",
)

print(response)


print("\n=== VERIFY NEW STRATEGY ===")

assert SCRIPT.exists(), (
    "Agent removed the test script."
)

content = SCRIPT.read_text(
    encoding="utf-8",
)

print(content)

assert "replan_local_source.txt" in content, (
    "Agent did not switch to the available local source."
)


print("\n=== INDEPENDENT EXECUTION ===")

# Remove previous output so verification proves
# the repaired script creates it.
if OUTPUT.exists():
    OUTPUT.unlink()

result = subprocess.run(
    [
        sys.executable,
        str(SCRIPT),
    ],
    capture_output=True,
    text=True,
)

print("Exit code:", result.returncode)
print("stdout:", result.stdout.strip())
print("stderr:", result.stderr.strip())

assert result.returncode == 0, (
    "Replanned strategy still fails."
)

assert OUTPUT.exists(), (
    "Replanned strategy did not create the output."
)

output_content = OUTPUT.read_text(
    encoding="utf-8",
).strip()

print("Output:", output_content)

assert output_content == "REPLAN RECOVERY WORKS", (
    "Replanned strategy produced incorrect output."
)


print("\nREPLAN RECOVERY TEST PASSED")
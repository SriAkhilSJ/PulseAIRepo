import sys
sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import os
from src.tools.file_tools import edit_file

# Test 1: invoke with config kwarg
cfg = {"configurable": {"workspace": ".", "thread_id": "test"}}
res = edit_file.invoke(
    {"path": "fixtures/live_benchmark_calc/calc_service.py", "old_text": "return round", "new_text": "return round"},
    config=cfg
)
print("Test 1 Result:", res)

# Test 2: invoke without config kwarg (should fail currently)
try:
    res2 = edit_file.invoke(
        {"path": "fixtures/live_benchmark_calc/calc_service.py", "old_text": "return round", "new_text": "return round"}
    )
    print("Test 2 Result:", res2)
except Exception as e:
    print("Test 2 Expected Failure:", type(e), e)

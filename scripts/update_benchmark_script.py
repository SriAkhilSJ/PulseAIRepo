p = r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\scripts\run_live_economics_benchmark.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

# Add imports for task_validation and retry_controller
old_imports = 'from src.tools.file_tools import read_file, list_files, search_code, edit_file'
new_imports = '''from src.tools.file_tools import read_file, list_files, search_code, edit_file
from src.graphs.task_validation import validate_database_lookup, validate_single_file_modification
from src.runtime.retry_controller import ToolRetryController'''

assert old_imports in text, "Target imports not found"
text = text.replace(old_imports, new_imports, 1)

# Fix dispatch_tool to invoke with config=cfg keyword argument cleanly
old_dispatch = '''def dispatch_tool(name: str, args: dict) -> str:
    workspace_root = str(os.getcwd())
    cfg = {"configurable": {"workspace": workspace_root, "thread_id": "live-bench"}}
    try:
        if name == "list_files":
            p = args.get("path", ".")
            return str(list_files.invoke({"path": p, "config": cfg}))
        elif name == "search_code":
            q = args.get("query", "")
            return str(search_code.invoke({"query": q, "config": cfg}))
        elif name == "read_file":
            p = args.get("path", "")
            kwargs = {"path": p, "config": cfg}
            if "start_line" in args and args["start_line"] is not None:
                kwargs["start_line"] = int(args["start_line"])
            if "end_line" in args and args["end_line"] is not None:
                kwargs["end_line"] = int(args["end_line"])
            return str(read_file.invoke(kwargs))
        elif name == "edit_file":
            p = args.get("path", "")
            old_t = args.get("old_text") or args.get("target") or ""
            new_t = args.get("new_text") or args.get("replacement") or ""
            return str(edit_file.invoke({"path": p, "old_text": old_t, "new_text": new_t, "config": cfg}))'''

new_dispatch = '''def dispatch_tool(name: str, args: dict) -> str:
    workspace_root = str(os.getcwd())
    cfg = {"configurable": {"workspace": workspace_root, "thread_id": "live-bench"}}
    try:
        if name == "list_files":
            p = args.get("path", ".")
            return str(list_files.invoke({"path": p}, config=cfg))
        elif name == "search_code":
            q = args.get("query", "")
            return str(search_code.invoke({"query": q}, config=cfg))
        elif name == "read_file":
            p = args.get("path", "")
            kwargs = {"path": p}
            if "start_line" in args and args["start_line"] is not None:
                kwargs["start_line"] = int(args["start_line"])
            if "end_line" in args and args["end_line"] is not None:
                kwargs["end_line"] = int(args["end_line"])
            return str(read_file.invoke(kwargs, config=cfg))
        elif name == "edit_file":
            p = args.get("path", "")
            old_t = args.get("old_text") or args.get("target") or ""
            new_t = args.get("new_text") or args.get("replacement") or ""
            return str(edit_file.invoke({"path": p, "old_text": old_t, "new_text": new_t}, config=cfg))'''

assert old_dispatch in text, "old_dispatch not found"
text = text.replace(old_dispatch, new_dispatch, 1)

# Update verify_task_1 and verify_task_2 to use deterministic validators
old_verifiers = '''def verify_task_1(session_result: dict) -> tuple[bool, str]:
    resp_text = (session_result.get("final_response") or "").lower()
    found_evidence = (
        "db.py" in resp_text or "settings.py" in resp_text 
        or "database_url" in resp_text or "sqlite" in resp_text
        or "engine" in resp_text
    )
    newly_mod = session_result.get("newly_modified_files", [])
    core_polluted = any("fixtures" not in f and "benchmark" not in f and "scripts" not in f for f in newly_mod)
    passed = found_evidence and not core_polluted
    reason = f"Evidence found: {found_evidence}, Core unpolluted: {not core_polluted}"
    return passed, reason

def verify_task_2(session_result: dict, trial_dir: str) -> tuple[bool, str]:
    test_path = os.path.join(trial_dir, "test_calc_service.py")
    res = subprocess.run(
        ["pytest", test_path, "-q"],
        capture_output=True,
        text=True
    )
    test_passed = (res.returncode == 0)
    
    newly_mod = session_result.get("newly_modified_files", [])
    scoped_ok = all(trial_dir.replace("\\\\", "/") in f.replace("\\\\", "/") or "benchmark" in f or "scripts" in f for f in newly_mod)
    passed = test_passed and scoped_ok
    reason = f"Pytest exit code: {res.returncode} (pass={test_passed}), Isolated scope ok: {scoped_ok}"
    return passed, reason'''

new_verifiers = '''def verify_task_1(session_result: dict) -> tuple[bool, str]:
    res = validate_database_lookup(
        final_response=session_result.get("final_response", ""),
        modified_files=session_result.get("newly_modified_files", []),
    )
    reason = f"Passed: {res.passed} (path={res.has_exact_file_path}, url={res.has_url_resolution}, engine={res.has_engine_instantiation}, reasons={res.failure_reasons})"
    return res.passed, reason

def verify_task_2(session_result: dict, trial_dir: str) -> tuple[bool, str]:
    res = validate_single_file_modification(
        trial_dir=trial_dir,
        target_rel_path="calc_service.py",
        test_rel_path="test_calc_service.py",
        modified_files=session_result.get("newly_modified_files", []),
        expected_patch_pattern=r"return\s+round\(\s*price\s*-\s*discount",
    )
    reason = f"Passed: {res.passed} (test_passed={res.tests_passed}, fix_verified={res.fix_verified_in_source}, clean={res.git_diff_clean}, reasons={res.failure_reasons})"
    return res.passed, reason'''

assert old_verifiers in text, "old_verifiers not found"
text = text.replace(old_verifiers, new_verifiers, 1)

with open(p, "w", encoding="utf-8") as f:
    f.write(text)

print("Updated scripts/run_live_economics_benchmark.py successfully!")


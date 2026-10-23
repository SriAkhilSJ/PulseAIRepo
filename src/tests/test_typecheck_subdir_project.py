"""G (field 2026-09-10, engine 94051109): typecheck_workspace was bound out
of the toolset for every task whose project lived ONE level below the session
workspace — the owner's log said "unavailable this session:
typecheck_workspace (no tsconfig.json in the workspace)" while the actual
project (D:\\TestCrusorAI\\test5) carried its own tsconfig.json + typescript.
The whole verification-gate family degraded with it.

hermes' discovery law (agent/coding_context.py): bounded — "root and its
immediate subdirs", a skip-list (_CODE_SCAN_SKIP_DIRS), an entries cap
(_CODE_SCAN_MAX_ENTRIES = 500), dot-dirs never descended. Both recipes
ported: root wins, else one bounded level down; ties prefer the folder with
package.json, then sort order.
"""
from src.tools.file_tools import find_typecheck_project_root, typecheck_workspace


def _project(tmp_path, name="test5", *, tsconfig=True, package=True, tsc_js=None):
    proj = tmp_path / name
    proj.mkdir(parents=True, exist_ok=True)
    if tsconfig:
        (proj / "tsconfig.json").write_text("{}", encoding="utf-8")
    if package:
        (proj / "package.json").write_text('{"name": "%s"}' % name, encoding="utf-8")
    if tsc_js is not None:
        bin_dir = proj / "node_modules" / "typescript" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "tsc").write_text(tsc_js, encoding="utf-8")
    return proj


def _invoke(workspace, thread="g-test"):
    return typecheck_workspace.invoke(
        {}, {"configurable": {"workspace": str(workspace), "thread_id": thread}}
    )


# ── the discovery helper (hermes bounds, ported) ──────────────────────────


def test_root_tsconfig_wins():
    import tempfile
    root = __import__("pathlib").Path(tempfile.mkdtemp())
    (root / "tsconfig.json").write_text("{}", encoding="utf-8")
    _project(root, "sub")
    assert find_typecheck_project_root(root) == root


def test_depth_one_discovery_finds_the_field_shape():
    import tempfile
    root = __import__("pathlib").Path(tempfile.mkdtemp())
    proj = _project(root, "test5")
    assert find_typecheck_project_root(root) == proj


def test_skip_list_and_dotdirs_are_never_projects():
    import tempfile
    root = __import__("pathlib").Path(tempfile.mkdtemp())
    _project(root, "node_modules")           # skipped by name
    _project(root, ".next")                  # dot-dir: never descended
    hidden = root / ".hidden"
    hidden.mkdir()
    (hidden / "tsconfig.json").write_text("{}", encoding="utf-8")
    assert find_typecheck_project_root(root) is None


def test_tie_prefers_package_json_then_sort_order():
    import tempfile
    root = __import__("pathlib").Path(tempfile.mkdtemp())
    plain = _project(root, "a-plain", package=False)
    packed = _project(root, "b-packed", package=True)
    assert find_typecheck_project_root(root) == packed  # package.json wins over sort
    assert plain.name == "a-plain"


def test_no_project_anywhere_is_none():
    import tempfile
    root = __import__("pathlib").Path(tempfile.mkdtemp())
    (root / "readme.md").write_text("not a project", encoding="utf-8")
    assert find_typecheck_project_root(root) is None


# ── the tool end-to-end on the owner's field shape ────────────────────────


def test_tool_typechecks_the_discovered_subdir_project(tmp_path, monkeypatch):
    _project(
        tmp_path, "test5",
        tsc_js='console.log("app/demo/page.tsx(3,5): error TS2304: Cannot find name gadget.");'
              'process.exit(2);\n',
    )
    out = _invoke(tmp_path)
    assert "❌ typecheck_workspace (project: test5/): 1 type error(s) found." in out
    assert "TS2304" in out


def test_tool_pass_receipt_names_the_project(tmp_path):
    _project(tmp_path, "test5", tsc_js="process.exit(0);\n")
    out = _invoke(tmp_path)
    assert out.startswith("✅ typecheck_workspace (project: test5/):")
    assert "0 errors" in out


def test_tool_root_project_receipt_stays_unsuffixed(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    _project(tmp_path, "test5")  # decoy subdir: root must win outright
    bin_dir = tmp_path / "node_modules" / "typescript" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "tsc").write_text("process.exit(0);\n", encoding="utf-8")
    out = _invoke(tmp_path)
    assert out == "✅ typecheck_workspace: tsc --noEmit passed with 0 errors."


def test_tool_names_missing_typescript_in_the_discovered_project(tmp_path):
    _project(tmp_path, "test5")  # tsconfig + package.json, NO node_modules
    out = _invoke(tmp_path)
    assert out.startswith("ℹ️ typecheck_workspace (project: test5/):")
    assert "typescript is not installed" in out


def test_tool_truly_empty_workspace_skip_message(tmp_path):
    out = _invoke(tmp_path)
    assert out.startswith("ℹ️ typecheck_workspace:")
    assert "no tsconfig.json at the workspace root or in its immediate project folders" in out


# ── the binding: the field bug itself ─────────────────────────────────────


def test_binding_keeps_typecheck_for_a_subdir_project(tmp_path):
    """The field bug: root D:\\TestCrusorAI (no tsconfig), project test5/ — the
    tool must STAY BOUND."""
    from src.graphs.chat_graph import _resolve_bound_tools

    _project(tmp_path, "test5")
    config = {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}}
    names = {t.name for t in _resolve_bound_tools(
        {"current_task": "typecheck everything"}, config)}
    assert "typecheck_workspace" in names


def test_binding_still_hides_typecheck_with_no_project(tmp_path):
    from src.graphs.chat_graph import _resolve_bound_tools

    config = {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}}
    names = {t.name for t in _resolve_bound_tools(
        {"current_task": "typecheck everything"}, config)}
    assert "typecheck_workspace" not in names


# ── pins: both call sites use the SAME discovery ──────────────────────────


def test_pins_discovery_is_shared_by_tool_and_hider():
    tool_src = open("src/tools/file_tools.py", encoding="utf-8").read()
    assert "def find_typecheck_project_root" in tool_src
    assert "project_root = find_typecheck_project_root(workspace_path)" in tool_src
    graph_src = open("src/graphs/chat_graph.py", encoding="utf-8").read()
    assert "from src.tools.file_tools import find_typecheck_project_root" in graph_src
    assert "if find_typecheck_project_root(workspace) is None:" in graph_src

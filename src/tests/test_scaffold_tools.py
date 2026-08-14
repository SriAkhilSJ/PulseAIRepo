from pathlib import Path


def test_scaffold_nextjs_preserves_provided_and_copy_first_files(tmp_path, monkeypatch):
    from src.tools.scaffold_tools import scaffold_nextjs
    workspace = tmp_path / "workspace"
    (workspace / "_provided").mkdir(parents=True)
    (workspace / "_provided" / "demo.tsx").write_text("SOURCE")
    (workspace / "src" / "components" / "ui").mkdir(parents=True)
    delivered = workspace / "src" / "components" / "ui" / "demo.tsx"
    delivered.write_text("DELIVERED")

    calls = []
    def fake_run(argv, *, cwd, timeout):
        calls.append(list(argv))
        if "create-next-app@latest" in argv:
            target = Path(cwd) / argv[2]
            (target / "src" / "app").mkdir(parents=True)
            (target / "src" / "app" / "page.tsx").write_text("PAGE")
            (target / "package.json").write_text('{"scripts":{"test":"echo ok"}}')
        return 0, "ok"

    monkeypatch.setattr("src.tools.scaffold_tools._run", fake_run)
    monkeypatch.setattr("src.tools.scaffold_tools.shutil.which", lambda name: name)
    result = scaffold_nextjs.invoke(
        {"packages": ["three", "@react-three/fiber"]},
        config={"configurable": {"workspace": str(workspace), "thread_id": "s"}},
    )
    assert result.startswith("✅")
    assert delivered.read_text() == "DELIVERED"
    assert (workspace / "_provided" / "demo.tsx").read_text() == "SOURCE"
    assert (workspace / "src" / "app" / "page.tsx").read_text() == "PAGE"
    assert calls[0][2].startswith("pulse-scaffold-")
    assert "--skip-install" in calls[0]
    assert calls[1][-3:] == ["three", "@react-three/fiber", "--legacy-peer-deps"]


def test_scaffold_refuses_existing_project(tmp_path, monkeypatch):
    from src.tools.scaffold_tools import scaffold_nextjs
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("user work")
    monkeypatch.setattr("src.tools.scaffold_tools.shutil.which", lambda name: name)
    result = scaffold_nextjs.invoke(
        {"packages": []},
        config={"configurable": {"workspace": str(workspace), "thread_id": "s"}},
    )
    assert "refused to merge" in result

"""One-shot prompt templates (hermes oneshot parity) — the express counter.

Pins: registry purity (templates never raise, empty variables render),
unknown-template errors name the valid set, ad-hoc fallback, execution
through an injectable invoke (default = cheap auxiliary tier), and the
bridge op being handled BEFORE session resolution (a one-shot must never
mint a session or touch the thread). Skill-linter tests live here too
(Phase 4): warn-only metadata checking at install time.
"""

import pytest

from src.agents import skills_hub as hub
from src.prompts import oneshot


class TestTemplateRegistry:
    def test_every_template_is_pure_and_never_raises(self):
        for name, fn in oneshot.PROMPT_TEMPLATES.items():
            system, user = fn({})  # empty variables must render, not raise
            assert system and isinstance(system, str), name
            assert user and isinstance(user, str), name
            full = fn({"input": "x", "diff": "d", "text": "t", "subject": "s",
                       "user": "u", "assistant": "a", "notes": "n", "context": "c"})
            assert all(isinstance(part, str) for part in full), name

    def test_catalog_lists_every_template_with_variables(self):
        listed = {row["name"] for row in oneshot.list_templates()}
        assert listed == set(oneshot.PROMPT_TEMPLATES)
        for row in oneshot.list_templates():
            assert row["description"] and row["variables"]

    def test_unknown_template_error_names_the_valid_set(self):
        res = oneshot.render_template("explode")
        assert not res["ok"] and "commit_message" in res["error"]

    def test_adhoc_requires_instructions(self):
        assert not oneshot.run_oneshot(template="")["ok"]
        assert "template or instructions" in oneshot.run_oneshot(template="")["error"]


class TestOneshotExecution:
    def test_template_mode_uses_injected_invoke(self):
        seen = {}

        def fake_invoke(prompt: str):
            seen["prompt"] = prompt
            class _R:
                content = "feat: add the thing\n\nwhy: because"
            return _R()

        res = oneshot.run_oneshot("commit_message", variables={"diff": "- added thing"}, invoke=fake_invoke)
        assert res["ok"] and "feat:" in res["text"]
        assert "- added thing" in seen["prompt"]

    def test_adhoc_mode_composes_ask_and_input(self):
        def fake_invoke(prompt: str):
            class _R:
                content = "done"
            return _R()

        res = oneshot.run_oneshot(
            instructions="Translate to French", variables={"input": "hello"},
            invoke=fake_invoke,
        )
        assert res["ok"] and res["text"] == "done"
        assert res["template"] == "adhoc"

    def test_provider_failure_is_an_error_not_an_exception(self):
        res = oneshot.run_oneshot("summarize", variables={"text": "x"},
                                  invoke=lambda _p: (_ for _ in ()).throw(RuntimeError("provider down")))
        assert not res["ok"] and "provider down" in res["error"]

    def test_empty_model_output_is_reported(self):
        class _R:
            content = "  "
        res = oneshot.run_oneshot("summarize", variables={"text": "x"}, invoke=lambda _p: _R())
        assert not res["ok"] and "empty" in res["error"]


class TestBridgeWiring:
    def test_oneshot_handled_before_session_resolution(self):
        """Same law as skills_hub_op: a one-shot has nothing to do with the
        chat thread — it must never go through session minting."""
        from pathlib import Path
        repo = Path(__file__).resolve().parents[2]
        src = (repo / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
        handle = src.split("def handle(self, frame: dict)")[1]
        assert handle.index('if kind == "oneshot":') < handle.index(
            'raw_workspace = frame.get("workspace")'
        )
        branch = handle.split('if kind == "oneshot":')[1].split("return True")[0]
        assert "run_oneshot" in branch and "oneshot_result" in branch

    def test_oneshot_bound_in_graph_protocol(self):
        from src.bridge.protocol import CLIENT_METHODS, SERVER_EVENTS
        assert "oneshot" in CLIENT_METHODS and "oneshot_result" in SERVER_EVENTS


class TestSkillLinter:
    """Phase 4: install-time metadata linter — warn, never block."""

    def test_bad_metadata_is_named_not_fatal(self):
        warnings = hub.lint_skill_metadata(
            "opaque-skill", {}, "body text", ["opaque-skill"]
        )
        joined = " ".join(warnings)
        assert "description" in joined and "never auto-activate" in joined

    def test_good_metadata_is_silent(self):
        frontmatter = {"description": "Does the thing well."}
        warnings = hub.lint_skill_metadata(
            "good-skill", frontmatter, "body", ["thing", "workflow"]
        )
        assert warnings == []

    def test_long_body_warns_about_the_cap(self):
        warnings = hub.lint_skill_metadata(
            "big", {"description": "d"}, "x" * 7000, ["t"]
        )
        assert any("capped at" in w for w in warnings)

    def test_install_result_carries_warnings(self, tmp_path, monkeypatch):
        from src.agents.skill_manager import SkillManager
        import io
        import tarfile

        manager = SkillManager(storage_path=str(tmp_path / "s.json"))
        monkeypatch.setattr("src.agents.skill_manager.skill_manager", manager)
        sha = "c" * 40
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            data = b"---\nname: opaque-skill\n---\n\nNo metadata at all.\n"
            ti = tarfile.TarInfo(name=f"r-{sha}/skills/opaque-skill/SKILL.md")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        blob = buf.getvalue()
        res = hub.install_skill(
            f"owner/repo@{sha}",
            manager=manager,
            hub_root=tmp_path / "hub",
            fetcher=lambda _url: blob,
        )
        assert res["ok"], res.get("error")
        assert res["warnings"], "a skill with no description/triggers must warn"

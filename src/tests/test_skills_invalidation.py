"""Skills invalidation seam (field 2026-10-01).

Pins the guarantee behind the UI copy "live in the skills index now":
a mutating skills op must be visible to the NEXT model call of RUNNING
sessions — no restart, no new session required.

Three caches outlived installs before the seam:
  1. the skills-index LRU + disk snapshot (skills_index)
  2. each live session view's cached system prompt (session._views)
  3. each live thread engine's cached "skills" layer (chat_graph._ENGINES;
     "skills" is NOT in VOLATILE_LAYERS and engines are long-lived)
The seam (skills_hub.notify_skills_changed) is wired into every mutating
hub op (install/update/remove/toggle) and skill_manage. These tests pin
the seam end to end, hermetically.
"""

from types import SimpleNamespace

import pytest

from src.agents import skills_hub as hub
from src.agents.skill_manager import SkillManager
from src.context import layer_policy
from src.prompts.hermes.skills_index import (
    build_skills_system_prompt,
    clear_skills_system_prompt_cache,
)

_SHA_A = "a" * 40

SKILL_TAR_HEADERS = {
    "trailofbits-skills-x/plugins/c-review/skills/c-review/SKILL.md": (
        "---\nname: c-review\ndescription: C/C++ security review.\n"
        "keywords: [security, review]\n---\n\n# C/C++ Security Review\n\n"
        "Resolve four parameters, make one Workflow call.\n"
    ).encode("utf-8"),
}


def _tar_bytes(entries: dict[str, bytes]) -> bytes:
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, data in entries.items():
            ti = tarfile.TarInfo(name=path)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    manager = SkillManager(storage_path=str(tmp_path / "skills.json"))
    monkeypatch.setattr("src.agents.skill_manager.skill_manager", manager)
    catalog = {
        "ok": True,
        "entries": [
            {
                "name": "c-review",
                "repo": "https://github.com/trailofbits/skills",
                "sha": _SHA_A,
                "subdir": "plugins/c-review/skills/c-review",
                "description": "C/C++ security review.",
                "category": "security",
                "trust": "curated",
            },
        ],
        "rejected": [],
    }
    archives = {_SHA_A: _tar_bytes(SKILL_TAR_HEADERS)}
    return {
        "manager": manager,
        "catalog": catalog,
        "hub_root": tmp_path / "hub",
        "fetcher": lambda url: archives[_SHA_A],
        "tmp": tmp_path,
    }


class TestSeamEndToEnd:
    def test_install_is_visible_to_the_next_prompt_build(self, env, monkeypatch):
        """The money test: build the index (cache warms), install through the
        SAME op path the bridge/UI uses, rebuild with identical arguments —
        the new skill must be there. Without the seam the second build
        returns the stale cached text and this fails."""
        skills_dir = env["tmp"] / "skills"
        skills_dir.mkdir()
        home = env["tmp"] / "home"
        home.mkdir()
        tools = ("skill_view", "hub_install")
        common = dict(
            available_tools=tools,
            skills_dir_override=skills_dir,
            home=home,
        )
        # the seam clears the snapshot under crusor_home(); point it at the
        # test home so the clear lands where the build reads
        monkeypatch.setattr("src.prompts.hermes.view.crusor_home", lambda: home)
        clear_skills_system_prompt_cache()
        try:
            before = build_skills_system_prompt(**common)
            assert "c-review" not in before

            res = hub.handle_hub_op(
                "install",
                frame={"source": "c-review"},
                catalog=env["catalog"],
                manager=env["manager"],
                hub_root=env["hub_root"],
                fetcher=env["fetcher"],
            )
            assert res["ok"], res.get("error")
            assert res.get("invalidated", {}).get("index") is True

            after = build_skills_system_prompt(**common)
            assert "c-review" in after
        finally:
            clear_skills_system_prompt_cache()

    def test_remove_is_visible_too(self, env, monkeypatch):
        skills_dir = env["tmp"] / "skills"
        skills_dir.mkdir()
        home = env["tmp"] / "home"
        home.mkdir()
        common = dict(available_tools=("skill_view",), skills_dir_override=skills_dir, home=home)
        monkeypatch.setattr("src.prompts.hermes.view.crusor_home", lambda: home)
        clear_skills_system_prompt_cache()
        try:
            hub.handle_hub_op(
                "install",
                frame={"source": "c-review"},
                catalog=env["catalog"],
                manager=env["manager"],
                hub_root=env["hub_root"],
                fetcher=env["fetcher"],
            )
            assert "c-review" in build_skills_system_prompt(**common)
            res = hub.handle_hub_op(
                "remove",
                frame={"name": "c-review"},
                catalog=env["catalog"],
                manager=env["manager"],
                hub_root=env["hub_root"],
            )
            assert res["ok"], res.get("error")
            assert "c-review" not in build_skills_system_prompt(**common)
        finally:
            clear_skills_system_prompt_cache()


class TestSeamInvalidators:
    def test_every_view_and_engine_is_invalidated(self, monkeypatch):
        """The seam walks ALL live views (session._views) and ALL live
        engines (chat_graph._ENGINES) — one stale instance re-introduces
        the bug this seam exists to kill."""
        from src.graphs import chat_graph
        from src.prompts.hermes import session as prompt_session
        from src.prompts.hermes import system_prompt as sp

        calls = {"views": [], "engines": []}
        monkeypatch.setattr(
            sp, "invalidate_system_prompt",
            lambda view: calls["views"].append(view),
        )

        class _FakeEngine:
            def __init__(self):
                self._layer_cache = {"skills": "stale", "history": "keep"}

            def invalidate_layer(self, name):
                calls["engines"].append(name)
                self._layer_cache.pop(name, None)

        view_a, view_b = object(), object()
        fake_engine = _FakeEngine()
        monkeypatch.setattr(prompt_session, "_views", {"v1": view_a, "v2": view_b}, raising=False)
        monkeypatch.setattr(chat_graph, "_ENGINES", {"t1": fake_engine}, raising=False)

        out = hub.notify_skills_changed()
        assert calls["views"] == [view_a, view_b]
        assert calls["engines"] == ["skills"]
        assert fake_engine._layer_cache == {"history": "keep"}  # only skills evicted
        assert out["index"] is True and out["views"] == 2 and out["engines"] == 1

    def test_seam_survives_broken_consumers(self, monkeypatch):
        """Fail-open: one poisoned view/engine must not stop the others, and
        the mutation that triggered the seam must never see an exception."""
        from src.graphs import chat_graph
        from src.prompts.hermes import session as prompt_session
        from src.prompts.hermes import system_prompt as sp

        def _boom(view):
            raise RuntimeError("poisoned view")

        class _Bad:
            def invalidate_layer(self, name):
                raise RuntimeError("poisoned engine")

        class _Good:
            def __init__(self):
                self.got = []

            def invalidate_layer(self, name):
                self.got.append(name)

        good = _Good()
        monkeypatch.setattr(sp, "invalidate_system_prompt", _boom)
        monkeypatch.setattr(
            prompt_session, "_views", {"bad": object(), "worse": object()}, raising=False
        )
        monkeypatch.setattr(
            chat_graph, "_ENGINES", {"bad": _Bad(), "good": good}, raising=False
        )
        out = hub.notify_skills_changed()  # must not raise
        assert good.got == ["skills"]
        assert out["views"] == 0 and out["engines"] == 1


class TestWiring:
    def test_skill_manage_fires_the_seam(self, monkeypatch):
        fired = []
        monkeypatch.setattr("src.agents.skills_hub.notify_skills_changed", lambda: fired.append(1))
        manager = SkillManager(storage_path=None)
        manager._skills = []
        manager.storage_path = str(manager.storage_path) + ".it-test"  # never the real store
        manager._skills = []
        monkeypatch.setattr("src.tools.skill_tools._manager", lambda: manager)
        from src.tools.skill_tools import skill_manage

        out = skill_manage.invoke({
            "action": "create", "name": "seam-test", "triggers": "x",
            "instruction": "body", "description": "d",
        })
        assert "created: seam-test" in out
        assert fired, "skill_manage must invalidate running sessions"

    def test_skills_layer_is_not_volatile_documented(self):
        """Why engine eviction matters: only git_context is volatile today.
        If 'skills' ever joins VOLATILE_LAYERS, seam step 3 becomes a
        no-op-by-design — update notify_skills_changed's docstring then."""
        assert "skills" not in layer_policy.VOLATILE_LAYERS

    def test_toggle_and_update_report_invalidation(self, env):
        env["manager"].add_skill("togglable", ["x"], "body")
        res = hub.handle_hub_op(
            "toggle", frame={"name": "togglable", "enabled": "off"},
            manager=env["manager"], hub_root=env["hub_root"],
        )
        assert res["ok"] and "invalidated" in res
        res2 = hub.handle_hub_op(
            "update", frame={"name": "togglable"},
            catalog=env["catalog"], manager=env["manager"], hub_root=env["hub_root"],
        )
        # not a hub skill -> refused cleanly, no invalidation claim
        assert not res2["ok"]

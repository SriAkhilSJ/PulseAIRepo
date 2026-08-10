"""D39 skill lifecycle: provenance, usage telemetry, curator transitions.

Mirrors hermes skill_usage.py + curator.py invariants:
  - only agent-created skills are auto-transitioned (created_by: "agent")
  - pinned skills exempt;   - archive never deletes
  - usage counts (use/view/patch) + last_activity_at persist
"""

import json
from datetime import datetime, timezone

from src.agents.skill_manager import SkillManager

_UTCNOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def _write(tmp_path, payload):
    p = tmp_path / "skills.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


def test_legacy_skills_are_normalized(tmp_path):
    path = _write(tmp_path, [
        {"name": "Old", "triggers": ["python"], "instruction": "use hints"},
    ])
    sm = SkillManager(storage_path=path)
    skill = sm.list_skills()[0]
    assert skill["created_by"] == "user"
    assert skill["pinned"] is False
    assert skill["state"] == "active"
    assert skill["use_count"] == 0
    assert skill["last_activity_at"] is None


def test_add_skill_user_vs_agent_provenance(tmp_path):
    path = _write(tmp_path, [])
    sm = SkillManager(storage_path=path)
    sm.add_skill("A", ["python"], "hints")
    sm.add_skill("B", ["ts"], "strict", created_by="agent", pinned=True)
    by_name = {s["name"]: s for s in sm.list_skills()}
    assert by_name["A"]["created_by"] == "user"
    assert by_name["A"]["pinned"] is False
    assert by_name["B"]["created_by"] == "agent"
    assert by_name["B"]["pinned"] is True


def test_add_skill_update_counts_as_patch_and_reactivates(tmp_path):
    path = _write(tmp_path, [])
    sm = SkillManager(storage_path=path)
    sm.add_skill("A", ["python"], "v1", created_by="agent")
    sm.list_skills()[0]["state"] = "archived"  # simulate prior transition
    sm.add_skill("A", ["python", "typing"], "v2", created_by="agent")
    skill = sm.list_skills()[0]
    assert skill["state"] == "active"
    assert skill["patch_count"] == 1
    assert "typing" in skill["triggers"]


def test_usage_telemetry_persists(tmp_path):
    path = _write(tmp_path, [])
    sm = SkillManager(storage_path=path)
    sm.add_skill("A", ["python"], "hints")
    sm.record_usage("A", "use")
    sm.record_usage("A", "use")
    sm.record_usage("A", "view")
    usage = sm.get_usage("A")
    assert usage["use_count"] == 2
    assert usage["view_count"] == 1
    # Telemetry must survive a reload (persisted to disk).
    sm2 = SkillManager(storage_path=path)
    assert sm2.get_usage("A")["use_count"] == 2
    assert sm2.get_usage("A")["last_activity_at"]


def test_relevant_skills_skip_archived_and_disabled_and_record_use(tmp_path):
    path = _write(tmp_path, [
        {"name": "Active", "triggers": ["python"], "instruction": "hints",
         "enabled": True, "state": "active", "created_by": "user"},
        {"name": "Archived", "triggers": ["python"], "instruction": "old",
         "enabled": True, "state": "archived", "created_by": "agent"},
        {"name": "Disabled", "triggers": ["python"], "instruction": "off",
         "enabled": False, "state": "active", "created_by": "user"},
    ])
    sm = SkillManager(storage_path=path)
    insts = sm.get_relevant_skills("write python code")
    assert len(insts) == 1
    assert sm.get_usage("Active")["use_count"] == 1
    assert sm.get_usage("Archived")["use_count"] == 0


def test_curator_transitions_only_agent_and_never_pinned(monkeypatch, tmp_path):
    path = _write(tmp_path, [])
    monkeypatch.setattr("src.agents.skill_manager._utcnow", lambda: _UTCNOW)
    sm = SkillManager(storage_path=path)
    base = _UTCNOW
    from datetime import timedelta
    sm._skills = [
        # agent skill idle 45 days -> stale
        {"name": "A", "triggers": [], "instruction": "x", "enabled": True,
         "created_by": "agent", "pinned": False, "state": "active",
         "last_activity_at": (base - timedelta(days=45)).isoformat()},
        # agent skill idle 120 days -> archived
        {"name": "B", "triggers": [], "instruction": "x", "enabled": True,
         "created_by": "agent", "pinned": False, "state": "active",
         "last_activity_at": (base - timedelta(days=120)).isoformat()},
        # agent skill idle 120 days but PINNED -> untouched
        {"name": "C", "triggers": [], "instruction": "x", "enabled": True,
         "created_by": "agent", "pinned": True, "state": "active",
         "last_activity_at": (base - timedelta(days=120)).isoformat()},
        # user skill idle 120 days -> untouched (not agent-created)
        {"name": "D", "triggers": [], "instruction": "x", "enabled": True,
         "created_by": "user", "pinned": False, "state": "active",
         "last_activity_at": (base - timedelta(days=120)).isoformat()},
        # agent skill idle 5 days -> stays active
        {"name": "E", "triggers": [], "instruction": "x", "enabled": True,
         "created_by": "agent", "pinned": False, "state": "active",
         "last_activity_at": (base - timedelta(days=5)).isoformat()},
    ]
    report = sm.curator_run(stale_after_days=30, archive_after_days=90)
    by_name = {s["name"]: s["state"] for s in sm.list_skills()}
    assert by_name["A"] == "stale"
    assert by_name["B"] == "archived"
    assert by_name["C"] == "active", "pinned agent skill must be exempt"
    assert by_name["D"] == "active", "user skill must be untouched"
    assert by_name["E"] == "active"
    moved = {r["name"] for r in report}
    assert moved == {"A", "B"}
    # Archive never deletes: B still exists and can only be removed explicitly.
    assert sm.remove_skill("B") is True, "B must still exist after archive"


def test_curator_report_and_archive_keeps_skill(tmp_path):
    from datetime import timedelta
    path = _write(tmp_path, [])
    sm = SkillManager(storage_path=path)
    base = datetime.now(timezone.utc)
    sm._skills = [
        {"name": "Z", "triggers": [], "instruction": "x", "enabled": True,
         "created_by": "agent", "pinned": False, "state": "active",
         "last_activity_at": (base - timedelta(days=200)).isoformat()},
    ]
    report = sm.curator_run(stale_after_days=30, archive_after_days=90)
    assert report[0]["to"] == "archived"
    assert sm.get_usage("Z")["state"] == "archived"
    # Archived skills are excluded from injection but still listed (never deleted).
    assert any(s["name"] == "Z" for s in sm.list_skills())
    assert sm.get_relevant_skills("anything z") == []


def test_skills_manifest_is_stable_index(tmp_path):
    path = _write(tmp_path, [
        {"name": "Hints", "triggers": ["python"], "instruction": "x",
         "enabled": True, "state": "active", "pinned": True},
        {"name": "Other", "triggers": ["ts"], "instruction": "y",
         "enabled": False},
    ])
    sm = SkillManager(storage_path=path)
    manifest = sm.skills_manifest()
    assert "Hints" in manifest
    assert "pinned" in manifest
    assert "Other" not in manifest, "disabled skills excluded from index"
    assert sm.skills_manifest() == manifest, "byte-stable within a session"
"""Bundled-skill discovery is recursive and taxonomy-aware.

The Architect library nests domain -> branch -> technology -> skill
(`skills/website-architect/frontend-development/react/nextjs/SKILL.md`).
Discovery must find every leaf at any depth, must ignore containers that carry
no `SKILL.md`, and must keep the flat legacy layout working unchanged.
"""
from __future__ import annotations

import textwrap

from src.agents.skill_manager import SkillManager


def _write(path, name: str, description: str, *, triggers: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = f"keywords: [{triggers}]\n" if triggers else ""
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: {description}
            {extra}metadata:
              crusor-domain: website-architect
              crusor-origin: original
            ---

            # {name}

            Body for {name}.
            """
        ),
        encoding="utf-8",
    )


def _manager(tmp_path) -> SkillManager:
    return SkillManager(storage_path=str(tmp_path / "skills.json"))


def test_nested_skill_is_discovered_at_any_depth(tmp_path):
    root = tmp_path / "skills"
    _write(
        root / "demo-domain" / "frontend-development" / "react" / "demo-nextjs" / "SKILL.md",
        "demo-nextjs",
        "Architect-level Next.js guidance.",
        triggers="nextjs, app router",
    )
    # A container with no SKILL.md must not become a skill.
    (root / "demo-domain" / "backend-development").mkdir(parents=True)

    mgr = _manager(tmp_path)
    mgr._load_bundled_skills(str(root))

    by_name = {s["name"]: s for s in mgr._skills}
    assert "demo-nextjs" in by_name
    assert "demo-domain" not in by_name
    assert "frontend-development" not in by_name
    skill = by_name["demo-nextjs"]
    assert skill["description"] == "Architect-level Next.js guidance."
    assert "nextjs" in skill["triggers"]
    assert skill["created_by"] == "bundled"
    assert skill["pinned"] is True
    assert "Body for demo-nextjs." in skill["instruction"]
    # Frontmatter never leaks into the injected instruction.
    assert "crusor-domain" not in skill["instruction"]


def test_flat_legacy_skills_still_load(tmp_path):
    root = tmp_path / "skills"
    _write(root / "systematic-debugging" / "SKILL.md", "systematic-debugging", "Debug workflow.")
    _write(
        root / "website-architect" / "frontend-development" / "react" / "react-core-architect" / "SKILL.md",
        "react-core-architect",
        "React application structure.",
    )

    mgr = _manager(tmp_path)
    mgr._load_bundled_skills(str(root))

    names = {s["name"] for s in mgr._skills}
    assert {"systematic-debugging", "react-core-architect"} <= names


def test_root_index_skill_md_is_not_a_skill(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    (root / "SKILL.md").write_text("# Skills index\n", encoding="utf-8")
    _write(root / "demo-nextjs" / "SKILL.md", "demo-nextjs", "Demo Next.js.")

    mgr = _manager(tmp_path)
    mgr._load_bundled_skills(str(root))

    names = {s["name"] for s in mgr._skills}
    assert "demo-nextjs" in names
    # The tree root's index file is a container, never a skill named after it.
    assert "skills" not in names


def test_duplicate_skill_names_are_not_loaded_twice(tmp_path):
    root = tmp_path / "skills"
    _write(root / "a" / "shared-name" / "SKILL.md", "shared-name", "First.")
    _write(root / "b" / "shared-name" / "SKILL.md", "shared-name", "Second.")

    mgr = _manager(tmp_path)
    mgr._load_bundled_skills(str(root))

    matches = [s for s in mgr._skills if s["name"] == "shared-name"]
    assert len(matches) == 1


def test_repo_architect_library_is_discoverable(tmp_path):
    """The shipped Website Architect pilot must load from the repo tree."""
    manager = _manager(tmp_path)
    names = {s["name"] for s in manager._skills}

    assert {
        "frontend-development-architect",
        "html-css-architect",
        "javascript-architect",
        "typescript-architect",
        "react-architect",
        "react-core-architect",
        "nextjs-architect",
        "react-router-architect",
        "react-state-management-architect",
        "react-ui-libraries-architect",
        "react-testing-architect",
        "vue-architect",
        "angular-architect",
        "svelte-architect",
        "astro-architect",
        "nodejs-architect",
        "threejs-architect",
        "python-architect",
        "flask-architect",
        "fastapi-architect",
        "django-architect",
        "tailwind-architect",
        "vite-architect",
        "playwright-architect",
        "tanstack-query-architect",
        "redux-toolkit-architect",
        "express-architect",
        "nestjs-architect",
        "fastify-architect",
        "accessibility-architect",
        "web-performance-architect",
        "i18n-architect",
        "forms-architect",
        "motion-architect",
        "seo-architect",
        "pwa-architect",
        "vitest-architect",
        "database-engineering-architect",
        "postgres-architect",
        "mongodb-architect",
        "redis-architect",
        "prisma-architect",
        "drizzle-architect",
        "api-development-architect",
        "rest-architect",
        "graphql-architect",
        "trpc-architect",
        "grpc-architect",
        "api-auth-architect",
        "rate-limiting-architect",
        "security-architect",
        "owasp-top10-architect",
        "authz-models-architect",
        "secrets-management-architect",
        "supply-chain-architect",
        "browser-security-architect",
        "testing-and-deployment-architect",
        "test-strategy-architect",
        "ci-cd-architect",
        "containerization-architect",
        "observability-architect",
        "release-strategy-architect",
        "incident-response-architect",
        "ui-ux-implementation-architect",
        "design-handoff-architect",
        "interaction-patterns-architect",
        "design-system-ops-architect",
        "content-microcopy-architect",
        "go-architect",
        "java-architect",
        "rust-architect",
        "dotnet-architect",
        "ruby-architect",
        "php-architect",
        "mobile-architect",
        "ios-architect",
        "android-architect",
        "react-native-architect",
        "flutter-architect",
        "mobile-release-architect",
        "desktop-architect",
        "electron-architect",
        "tauri-architect",
        "native-desktop-architect",
        "desktop-distribution-architect",
        "cloud-and-devops-architect",
        "aws-architect",
        "kubernetes-architect",
        "terraform-architect",
        "serverless-architect",
        "reliability-architect",
        "cost-optimization-architect",
        "ai-ml-architect",
        "llm-app-architect",
        "rag-architect",
        "evals-architect",
        "inference-serving-architect",
        "mlops-architect",
        "agent-architect",
        "data-engineering-architect",
        "batch-pipeline-architect",
        "streaming-architect",
        "warehouse-architect",
        "orchestration-architect",
        "data-quality-architect",
        "analytics-engineering-architect",
        "ios-swiftui-architect",
        "android-compose-architect",
        "mobile-offline-sync-architect",
        "mobile-security-architect",
        "mobile-performance-architect",
        "mobile-testing-architect",
        "mobile-accessibility-architect",
        "desktop-ipc-architect",
        "desktop-offline-storage-architect",
        "desktop-security-architect",
        "desktop-update-architect",
        "gcp-architect",
        "azure-architect",
        "cloudflare-architect",
        "iam-architect",
        "multi-account-architect",
        "secrets-and-keys-architect",
        "vpc-networking-architect",
        "dns-and-edge-architect",
        "network-security-architect",
        "ec2-architect",
        "ecs-architect",
        "lambda-architect",
        "autoscaling-architect",
        "object-storage-architect",
        "managed-databases-architect",
        "messaging-architect",
        "caching-architect",
        "pulumi-architect",
        "cloudformation-architect",
        "ansible-architect",
        "helm-architect",
        "gitops-architect",
        "service-mesh-architect",
        "kubernetes-security-architect",
        "platform-engineering-architect",
        "sre-observability-architect",
        "chaos-engineering-architect",
        "backup-and-dr-architect",
        "cloud-incident-response-architect",
    } <= names
    # Existing flat process skills must survive the recursive discovery change.
    assert "systematic-debugging" in names


def test_architect_leaves_conform_to_the_agent_skills_spec():
    """Every shipped Architect skill, in every domain: name==dir, spec-safe
    slug, bounded description and body, mandatory provenance."""
    import re
    from pathlib import Path

    from src.agents.skill_manager import (
        _BUNDLED_INSTRUCTION_CAP,
        _parse_skill_frontmatter,
    )

    slug = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    leaves = []
    for path in sorted(Path("skills").rglob("SKILL.md")):
        frontmatter, body = _parse_skill_frontmatter(path.read_text(encoding="utf-8"))
        if not (frontmatter.get("metadata") or {}).get("crusor-domain"):
            continue  # legacy flat skills predate the library contract
        leaves.append((path, frontmatter, body))
    assert leaves, "Architect library is missing"

    for path, frontmatter, body in leaves:
        name = str(frontmatter.get("name", ""))
        description = str(frontmatter.get("description", ""))
        assert name == path.parent.name, f"{path}: name must equal directory"
        assert slug.match(name), f"{path}: invalid skill slug {name!r}"
        assert 0 < len(description) <= 1024, f"{path}: description length"
        assert len(body) <= _BUNDLED_INSTRUCTION_CAP, (
            f"{path}: body {len(body)} exceeds injection cap "
            f"{_BUNDLED_INSTRUCTION_CAP} and would be silently truncated"
        )
        assert frontmatter.get("metadata", {}).get("crusor-origin"), path


def test_skill_names_unique_and_crusor_path_matches_location():
    """Names are globally unique and crusor-path tells the truth about depth."""
    from pathlib import Path

    from src.agents.skill_manager import _parse_skill_frontmatter

    root = Path("skills")
    seen: dict[str, Path] = {}
    checked = 0
    for path in sorted(root.rglob("SKILL.md")):
        frontmatter, _ = _parse_skill_frontmatter(path.read_text(encoding="utf-8"))
        name = str(frontmatter.get("name", ""))
        if not name:
            continue  # legacy docs-style SKILL.md without frontmatter
        assert name not in seen, f"{name} declared in both {seen[name]} and {path}"
        seen[name] = path

        if not (frontmatter.get("metadata") or {}).get("crusor-domain"):
            continue
        expected = path.parent.relative_to(root).as_posix()
        declared = frontmatter.get("metadata", {}).get("crusor-path")
        assert declared == expected, f"{path}: crusor-path {declared!r} != {expected!r}"
        checked += 1
    assert checked >= 80


FRONTEND_CAPABILITIES = {
    "markup and cascade": "html-css-architect",
    "language runtime": "javascript-architect",
    "type contracts": "typescript-architect",
    "styling system": "tailwind-architect",
    "build and bundling": "vite-architect",
    "motion": "motion-architect",
    "offline and install": "pwa-architect",
    "accessibility": "accessibility-architect",
    "performance": "web-performance-architect",
    "indexability": "seo-architect",
    "internationalisation": "i18n-architect",
    "forms": "forms-architect",
    "unit and component tests": "vitest-architect",
    "end-to-end tests": "playwright-architect",
    "react": "react-architect",
    "vue": "vue-architect",
    "angular": "angular-architect",
    "svelte": "svelte-architect",
    "astro": "astro-architect",
    "node runtime": "nodejs-architect",
    "3d": "threejs-architect",
}


def test_frontend_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {cap: skill for cap, skill in FRONTEND_CAPABILITIES.items() if skill not in available}
    assert not missing, f"frontend capabilities without a skill: {missing}"
    assert len(FRONTEND_CAPABILITIES) >= 20


DATABASE_CAPABILITIES = {
    "relational core": "postgres-architect",
    "document store": "mongodb-architect",
    "cache and ephemeral state": "redis-architect",
    "typescript schema and migrations": "prisma-architect",
    "sql-first typed queries": "drizzle-architect",
    "engine-agnostic data direction": "database-engineering-architect",
}


def test_database_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in DATABASE_CAPABILITIES.items() if s not in available}
    assert not missing, f"data-layer capabilities without a skill: {missing}"


API_CAPABILITIES = {
    "contract and versioning direction": "api-development-architect",
    "resource-oriented http": "rest-architect",
    "client-driven graph": "graphql-architect",
    "typescript-only rpc": "trpc-architect",
    "service-to-service streaming": "grpc-architect",
    "identity and authorization": "api-auth-architect",
    "quotas and abuse": "rate-limiting-architect",
}


def test_api_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in API_CAPABILITIES.items() if s not in available}
    assert not missing, f"API capabilities without a skill: {missing}"


SECURITY_CAPABILITIES = {
    "threat modelling and boundaries": "security-architect",
    "vulnerability classes": "owasp-top10-architect",
    "permission modelling and enforcement": "authz-models-architect",
    "credential custody and rotation": "secrets-management-architect",
    "dependency and pipeline integrity": "supply-chain-architect",
    "browser boundaries and headers": "browser-security-architect",
}


def test_security_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in SECURITY_CAPABILITIES.items() if s not in available}
    assert not missing, f"security capabilities without a skill: {missing}"


DELIVERY_CAPABILITIES = {
    "test portfolio and trust": "test-strategy-architect",
    "pipeline and gates": "ci-cd-architect",
    "packaging and environments": "containerization-architect",
    "telemetry and alerting": "observability-architect",
    "rollout and rollback": "release-strategy-architect",
    "incidents and postmortems": "incident-response-architect",
    "quality-to-production direction": "testing-and-deployment-architect",
}


def test_delivery_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in DELIVERY_CAPABILITIES.items() if s not in available}
    assert not missing, f"delivery capabilities without a skill: {missing}"


UI_CAPABILITIES = {
    "design to code contract": "design-handoff-architect",
    "behaviour and state patterns": "interaction-patterns-architect",
    "component system operation": "design-system-ops-architect",
    "interface words": "content-microcopy-architect",
    "implementation direction": "ui-ux-implementation-architect",
}


def test_ui_branch_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in UI_CAPABILITIES.items() if s not in available}
    assert not missing, f"UI capabilities without a skill: {missing}"


def test_website_architect_tree_is_complete():
    """Every planned branch carries a SKILL.md of its own."""
    from pathlib import Path

    root = Path("skills/website-architect")
    planned = [
        "frontend-development-architect",
        "backend-development-architect",
        "database-engineering-architect",
        "api-development-architect",
        "ui-ux-implementation-architect",
        "security-architect",
        "testing-and-deployment-architect",
    ]
    missing = [b for b in planned if not (root / b / "SKILL.md").is_file()]
    assert not missing, f"branches without a branch-level skill: {missing}"


BACKEND_CAPABILITIES = {
    "python services": "python-architect",
    "node services": "nodejs-architect",
    "go services": "go-architect",
    "jvm services": "java-architect",
    "rust services": "rust-architect",
    "dotnet services": "dotnet-architect",
    "ruby services": "ruby-architect",
    "php services": "php-architect",
    "framework leaves (python)": "flask-architect",
    "framework leaves (node)": "nestjs-architect",
}


def test_backend_branch_covers_every_language():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in BACKEND_CAPABILITIES.items() if s not in available}
    assert not missing, f"backend capabilities without a skill: {missing}"


MOBILE_CAPABILITIES = {
    "platform choice and shared architecture": "mobile-architect",
    "apple platform": "ios-architect",
    "android platform": "android-architect",
    "shared typescript stack": "react-native-architect",
    "shared dart stack": "flutter-architect",
    "stores, signing, rollout": "mobile-release-architect",
    "ios screens and state": "ios-swiftui-architect",
    "android screens and state": "android-compose-architect",
    "offline store and conflicts": "mobile-offline-sync-architect",
    "tokens, biometrics, tampering": "mobile-security-architect",
    "start-up, jank, memory, size": "mobile-performance-architect",
    "test layers and device matrix": "mobile-testing-architect",
    "screen readers and scaling": "mobile-accessibility-architect",
}


def test_mobile_domain_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in MOBILE_CAPABILITIES.items() if s not in available}
    assert not missing, f"mobile capabilities without a skill: {missing}"


def test_every_domain_has_a_crown_skill():
    """Each top-level domain directory in the library states its own entry
    point, so an agent landing on `skills/<domain>/` always has a book there."""
    from pathlib import Path

    from src.agents.skill_manager import _parse_skill_frontmatter

    domains = set()
    for path in Path("skills").rglob("SKILL.md"):
        frontmatter, _ = _parse_skill_frontmatter(path.read_text(encoding="utf-8"))
        domain = (frontmatter.get("metadata") or {}).get("crusor-domain")
        if domain:
            domains.add(str(domain))
    assert domains >= {
        "website-architect", "mobile-architect", "desktop-architect",
        "cloud-and-devops-architect",
        "ai-ml-architect",
        "data-engineering-architect",
    }
    for domain in sorted(domains):
        crown = Path("skills") / domain / "SKILL.md"
        assert crown.is_file(), f"domain {domain!r} has no crown skill at {crown}"
        frontmatter, _ = _parse_skill_frontmatter(crown.read_text(encoding="utf-8"))
        assert frontmatter.get("name") == domain


DESKTOP_CAPABILITIES = {
    "runtime choice and process boundaries": "desktop-architect",
    "web stack runtime": "electron-architect",
    "system webview runtime": "tauri-architect",
    "platform-native stack": "native-desktop-architect",
    "signing, packaging, updates": "desktop-distribution-architect",
    "typed bridge to the privileged core": "desktop-ipc-architect",
    "local database and durability": "desktop-offline-storage-architect",
    "keychain, CSP and local exposure": "desktop-security-architect",
    "channels, staged rollout, migrations": "desktop-update-architect",
}


def test_desktop_domain_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in DESKTOP_CAPABILITIES.items() if s not in available}
    assert not missing, f"desktop capabilities without a skill: {missing}"


CLOUD_CAPABILITIES = {
    "topology, identity and cost direction": "cloud-and-devops-architect",
    "provider primitives": "aws-architect",
    "container orchestration": "kubernetes-architect",
    "infrastructure as code": "terraform-architect",
    "scale-to-zero workloads": "serverless-architect",
    "SLOs, HA and DR": "reliability-architect",
    "spend attribution and unit economics": "cost-optimization-architect",
    "google cloud": "gcp-architect",
    "microsoft azure": "azure-architect",
    "edge compute and perimeter": "cloudflare-architect",
    "roles, federation, break-glass": "iam-architect",
    "account structure and vending": "multi-account-architect",
    "keys, rotation, leak response": "secrets-and-keys-architect",
    "VPC topology and egress": "vpc-networking-architect",
    "zones, TTL, certificates": "dns-and-edge-architect",
    "segmentation and inspection": "network-security-architect",
    "virtual machines": "ec2-architect",
    "containers without Kubernetes": "ecs-architect",
    "AWS functions": "lambda-architect",
    "elasticity control loops": "autoscaling-architect",
    "buckets, lifecycle, egress": "object-storage-architect",
    "managed engines and failover": "managed-databases-architect",
    "queues, topics, DLQs": "messaging-architect",
    "cache layers and invalidation": "caching-architect",
    "IaC in a real language": "pulumi-architect",
    "native AWS IaC": "cloudformation-architect",
    "configuring existing servers": "ansible-architect",
    "chart packaging": "helm-architect",
    "desired state from git": "gitops-architect",
    "uniform service traffic policy": "service-mesh-architect",
    "cluster hardening and tenancy": "kubernetes-security-architect",
    "internal developer platform": "platform-engineering-architect",
    "telemetry, dashboards, alerts": "sre-observability-architect",
    "resilience experiments": "chaos-engineering-architect",
    "RPO/RTO and restore drills": "backup-and-dr-architect",
    "managing an incident": "cloud-incident-response-architect",
}


def test_cloud_domain_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in CLOUD_CAPABILITIES.items() if s not in available}
    assert not missing, f"cloud capabilities without a skill: {missing}"


AI_ML_CAPABILITIES = {
    "model boundary, envelope and eval-first ordering": "ai-ml-architect",
    "prompting, structured output and routing": "llm-app-architect",
    "grounded answers over a private corpus": "rag-architect",
    "quality measurement and regression gates": "evals-architect",
    "latency, throughput and self-hosting": "inference-serving-architect",
    "training pipelines and model lifecycle": "mlops-architect",
    "multi-step autonomy and tool permissions": "agent-architect",
}


def test_ai_ml_domain_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in AI_ML_CAPABILITIES.items() if s not in available}
    assert not missing, f"ai/ml capabilities without a skill: {missing}"


DATA_CAPABILITIES = {
    "source-to-consumer topology and freshness envelope": "data-engineering-architect",
    "batch and incremental loads": "batch-pipeline-architect",
    "continuous event processing": "streaming-architect",
    "analytical storage and modelling": "warehouse-architect",
    "scheduling, SLAs and recovery": "orchestration-architect",
    "contracts, tests and incidents": "data-quality-architect",
    "SQL transformation layer and metrics": "analytics-engineering-architect",
}


def test_data_domain_covers_every_capability():
    from src.agents.skill_manager import SkillManager

    sm = SkillManager(storage_path=str(__import__("tempfile").NamedTemporaryFile(suffix=".json").name))
    available = {s["name"] for s in sm.list_skills() if s.get("created_by") == "bundled"}
    missing = {c: s for c, s in DATA_CAPABILITIES.items() if s not in available}
    assert not missing, f"data capabilities without a skill: {missing}"

---
name: supply-chain-architect
description: Architect-level software supply-chain security — dependency policy and pinning, lockfile and audit enforcement, CI/CD hardening with least-privilege tokens, build provenance and artefact signing, and the review gate that catches a compromised package before it ships. Use when a project installs dependencies or has a pipeline.
license: MIT
compatibility: npm/pnpm/yarn, pip/uv, Go modules, Cargo; GitHub Actions or equivalent
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/security-architect/supply-chain-architect
  crusor-origin: original
  crusor-sources: "slsa.dev; owasp.org/www-project-top-10-ci-cd-security-risks; docs.github.com/actions/security-guides"
  crusor-triggers: "supply chain, dependencies, lockfile, npm audit, slsa, provenance, ci security, ci pipeline, pipeline hardening, typosquatting, sbom"
  crusor-verified-on: "2026-10-30"
---

# Supply Chain Architect

You do not ship your code; you ship **your code plus everything it imports plus
everything your pipeline runs**. Both halves are attack surface.

## When to use

- Any project with third-party dependencies or an automated pipeline.
- Adding a new dependency, or reviewing one someone added.
- Hardening CI, release, or artefact distribution.

## When NOT to use

- A zero-dependency script — the policy below is still cheap, just short.

## Decision 1 — Dependency policy

- Every dependency has a justification: what it saves, who maintains it, how big
  it is. "It was convenient" is not a justification.
- Prefer the standard library, then a well-maintained single-purpose package,
  then a framework you already depend on.
- Check: maintainer count, last release, open critical issues, install scripts,
  transitive size.
- Typosquatting is real: verify the exact package name against the registry, not
  a blog post.
- Remove unused dependencies; each one is a permanent liability.

## Decision 2 — Pinning and audit

- Lockfiles committed. Exact versions in production; ranges only for libraries
  you publish.
- Audit runs in CI and blocks on high severity, with a documented exception
  process (owner + expiry).
- Automated update PRs are welcome **only** with the test suite as the gate.
- SBOM generated per release; you must be able to answer "are we affected?" in
  minutes, not days.

## Decision 3 — Install-time risk

- Install scripts are code execution: disable by default where the ecosystem
  allows, allow-list when required.
- Private registries/proxies for internal packages; scope tokens narrowly.
- Never install from a URL or a git ref in production builds unless pinned to a
  commit and reviewed.

## Decision 4 — CI/CD hardening

| Risk | Control |
|---|---|
| stolen CI token | least-privilege, short-lived, per-job permissions |
| untrusted PR runs code with secrets | no secrets on fork PRs, `pull_request` not `pull_request_target` |
| third-party action compromised | pin actions to a commit SHA, not a tag |
| pipeline output leaks | mask secrets, restrict artifact access |
| build machine persisted | ephemeral runners |

- Workflow files are code: reviewed, owned, and minimal.
- Deploy credentials live in the platform, never in the repo.

## Decision 5 — Provenance and release

- Build once, promote the same artefact through environments — no rebuild per
  environment.
- Sign artefacts/images; verify signatures at deploy.
- Publish checksums; consumers verify them.
- Releases are reproducible or at least traceable: source commit → artefact →
  deploy, linked.

## Failure modes at scale

- `latest` tags in production: the next release is a silent code change.
- A CI token with org-wide write access, in a job that runs PR code.
- An action pinned to `@v3` — the tag can be moved by the maintainer or an
  attacker.
- No SBOM: a zero-day lands and nobody knows if they use the package.
- 40 transitive dependencies added by one convenience import.

## Verification receipts

1. Dependency inventory with justification for each direct dependency.
2. Lockfile diff reviewed in PRs; `--frozen-lockfile` in CI.
3. Audit + SBOM in the release pipeline.
4. CI permissions review: per-job scopes, SHA-pinned actions, no secrets on
   forks.
5. Artefact signature verified at deploy, once, in front of the team.

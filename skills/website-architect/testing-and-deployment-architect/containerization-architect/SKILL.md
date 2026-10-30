---
name: containerization-architect
description: Architect-level container and environment design — image layering and reproducibility, runtime configuration versus baked config, resource limits and health checks, local-to-production parity, and the image failures (bloat, root user, mutable tags) that break deploys. Use when packaging a service.
license: MIT
compatibility: Docker/OCI images; Kubernetes or a PaaS
metadata:
  crusor-domain: website-architect
  crusor-path: testing-and-deployment-architect/containerization-architect
  crusor-origin: original
  crusor-sources: "docs.docker.com/build/building/best-practices; 12factor.net; kubernetes.io/docs/concepts/configuration"
  crusor-triggers: "docker, container, dockerfile, image, kubernetes, k8s, deployment topology, healthcheck, environment parity"
  crusor-verified-on: "2026-10-30"
---

# Containerization Architect

A container is **a shipping box, not a machine**. If configuration is baked into
it, you have rebuilt "works on my machine" with extra steps.

## When to use

- Packaging a service for deployment, or consolidating a messy Dockerfile.
- Local and production environments disagree.
- Images are large, slow to build, or run as root.

## When NOT to use

- A static site on a CDN — a container adds cost for nothing.

## Decision 1 — Image design

- Multi-stage build: build deps in one stage, runtime artefact + runtime deps in
  the final image.
- Distroless/slim base images; pin by digest, not `latest`.
- Non-root user, read-only root filesystem where possible.
- One process per container; no supervisord launching three services.
- `.dockerignore` as important as `.gitignore` — never copy `node_modules`,
  `.git`, or secrets into the build context.

## Decision 2 — Reproducibility

- Deterministic install (`npm ci`, `pip install -r` with hashes, lockfiles).
- Build args used for build-time constants only; secrets never as `ARG`.
- Same image digest runs in staging and production.
- Build cache keyed on dependency manifests, invalidated by source changes.

## Decision 3 — Configuration

| Kind | Where |
|---|---|
| credentials, endpoints | environment variables / mounted secrets |
| feature flags | runtime config service |
| build-time identity (version, commit) | label + `ARG`, baked |
| files that change per environment | mounted config, not baked |

- The image is immutable; the environment supplies the differences.
- Startup validates config and fails fast with a clear message.
- Never bake `.env` files into layers — history remembers.

## Decision 4 — Runtime behaviour

- Health: liveness (is the process alive) vs readiness (can it serve traffic).
- Graceful shutdown: handle `SIGTERM`, stop accepting, drain, exit; align with
  the orchestrator's grace period.
- Resource requests and limits set from measurement; a memory limit without a
  request causes eviction surprises.
- Logs to stdout/stderr as structured JSON; no files inside the container.

## Decision 5 — Environment parity

- Same base image, same runtime version, same migrations path locally and in
  production.
- Local compose defines the same services (DB, queue, cache) with the same
  versions.
- Differences that remain are documented — "works in docker" is a hypothesis
  until staging proves it.

## Failure modes at scale

- 1.8 GB image because build tools shipped to runtime.
- Container runs as root; a compromised dependency owns the host namespace.
- `latest` tag deployed twice, two different applications.
- Secrets passed as build args, visible in image history.
- Readiness probe that returns 200 while the DB is unreachable.

## Verification receipts

1. Image size and layer breakdown; build time recorded.
2. `docker history` shows no secrets and no build tooling in the final stage.
3. Runs as non-root; drop capabilities verified.
4. SIGTERM drill: in-flight request completes, process exits within the grace
   period.
5. Readiness test with a dependency down → not ready.

---
name: rest-graphql-debug
description: "Layer-by-layer REST/GraphQL API debugging with curl."
version: 1.1.0
author: Hermes Agent, ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [api, rest, graphql, http, debugging, curl, integration]
    related_skills: [systematic-debugging, browser-connector]
---

**Triggers:** rest api, graphql, curl, endpoint, http client, api integration, api call, 401, 403, 404, 500, api debug, rate limit

# REST / GraphQL API Debugging

## Overview

Debug HTTP API issues by walking the layers in order, never skipping: a 200 OK can hide broken data; a 500 can mask a one-character auth typo. For **client-side API behavior in the browser** (CORS, devtools evidence), pair with `browser-connector`.

Skip for UI rendering, DB query tuning, or DNS/firewall infra.

## Core Principle: Isolate the layer, then fix

```
1. Connectivity   → can we reach the host at all?
1.5 Timeouts      → connect-slow vs read-slow?
2. TLS/SSL        → cert valid and trusted?
3. Auth           → credentials correct and unexpired?
4. Request format → payload shape match server expectations?
5. Response parse → does our code accept what came back?
6. Semantics      → does the data mean what we assume?
```

## Quickstart (through `run_terminal`)

### REST

```bash
curl -v https://api.example.com/users/1            # verbose exchange
curl -X POST https://api.example.com/users -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d '{"name":"test"}'
curl -sI https://api.example.com/health            # headers only
curl -s https://api.example.com/users | python3 -m json.tool
```

### GraphQL

```bash
curl -X POST https://api.example.com/graphql -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d '{"query":"{ user(id: 1) { name email } }"}'
```

**GraphQL gotcha:** servers often return HTTP 200 even when the query failed. Always inspect the `errors` field regardless of status code:

```python
data = resp.json()
if data.get("errors"):
    for err in data["errors"]:
        print(f"GraphQL error: {err['message']} (path: {err.get('path')})")
```

## Layered Debug Flow

**1. Connectivity** — `curl -v --connect-timeout 5 https://host/health`. Failures: DNS, firewall, VPN, proxy missing (`nslookup`, check `HTTP(S)_PROXY`).

**1.5. Timeouts** — connect-slow (network/DNS) vs read-slow (server hang): `curl -o /dev/null -s -w 'connect: %{time_connect}s ttfb: %{time_starttransfer}s total: %{time_total}s\n' URL`. Always set `timeout=(3.05, 30)` (connect, read) in requests code.

**2. TLS** — `curl -v` shows cert errors. `SSL: CERTIFICATE_VERIFY_FAILED` on corporate networks → proxy MITM; never ship `verify=False` as the fix, root-cause the trust store.

**3. Auth** — decode the JWT: `echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool` — check `exp`, `iss`, `aud`, scopes. 401 = unauthenticated (bad/expired token); 403 = authenticated but unauthorized (missing scope/role).

**4. Request format** — diff your payload against the API's documented shape; check `Content-Type` (JSON APIs reject form-encoded bodies); trailing slashes; required headers (`Idempotency-Key`, `X-Requested-With`).

**5. Response parse** — print `resp.status_code`, `dict(resp.headers)`, `resp.text[:500]` BEFORE `.json()`. HTML in a JSON-expected field = proxy error page, not an API response.

**6. Semantics** — empty data with 200? check pagination params, tenant filters, soft-deletes, timezone/date-string boundaries.

## Rules

- Reproduce with the smallest possible curl before touching application code.
- Never log full tokens; redact `Authorization` in anything shown to the user.
- Fix at the failing layer — don't add retries around a bug, don't catch-and-swallow.
- 429s: read `Retry-After`, honor it, check rate-limit headers (`X-RateLimit-Remaining`) before assuming a bug.

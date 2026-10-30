---
name: mobile-analytics-architect
description: Architect-level mobile analytics and experimentation — event taxonomy and naming, identity and session semantics, feature flags and remote config, experiment assignment and exposure logging, and the consent and retention rules that keep the data lawful. Use when product decisions depend on what users do in the app.
license: MIT
compatibility: Amplitude, Mixpanel, Firebase, Segment, LaunchDarkly, Statsig
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/quality-architect/mobile-analytics-architect
  crusor-origin: original
  crusor-sources: "segment.com/docs; launchdarkly.com/blog; amplitude.com/docs/data-taxonomy; firebase.google.com/docs/remote-config"
  crusor-triggers: "mobile analytics, event tracking, feature flags, remote config, a/b test, experiment exposure, event taxonomy, session tracking"
  crusor-verified-on: "2026-10-30"
---

# Mobile Analytics Architect

Analytics is **a schema you ship**. Bad event names are technical debt you cannot
refactor — the history is already written.

## When to use

- Product decisions rely on in-app behaviour.
- Feature flags or experiments run on device.
- Existing analytics has duplicate events and unanswerable questions.

## When NOT to use

- A feature with no measurable decision attached.
- Pre-product-market-fit where the data set is too small to be useful.

## Decision 1 — Taxonomy

```
Object Action   → e.g. Checkout Completed, Video Played, Search Performed
properties      → namespaced, typed, documented (plan, duration_ms, source)
```

- Past tense for things that happened; one event per user intent.
- No free-form strings; enums with a documented value list.
- Properties are typed and bounded: no raw search queries unless deliberately.
- A tracking plan in the repo, reviewed like an API contract.

## Decision 2 — Identity

- Anonymous device id until login; then merge identities through the vendor's identify
  call.
- Define session semantics: platform timeout, background behaviour, and what counts as
  new.
- Account-level and device-level properties are different things; do not conflate.
- Logout must reset identity without losing pre-login events.

## Decision 3 — Flags and config

- Flags for release control (kill switch) are separate from experiment flags.
- Remote config defaults ship in the binary; a config outage must not break the app.
- Flag evaluation cached; a failed fetch falls back, never blocks startup.
- Flag lifecycle: created → rolled out → archived. Stale flags accumulate and confuse.

## Decision 4 — Experiments

- Assignment at a stable unit (device or account) via the flagging tool, not random in
  code.
- Log **exposure** when the user actually sees the variant — analysis on assignment
  alone is biased.
- One primary metric and guardrails, decided before launch.
- Sample size calculated in advance; peeking at results invalidates them.

## Decision 5 — Privacy

- Consent before collection in regulated regions; analytics SDKs initialise after
  consent.
- No PII in event properties; hashed ids where correlation is needed.
- Retention per policy; cohort data ages out.
- Deletion requests must reach the analytics vendor, not just your backend.

## Failure modes at scale

- Three spellings of the same event; the funnel is unbuildable.
- Experiment analysed on assignment, not exposure; result is wrong.
- Remote config fetched before first paint; cold start blocked by a network call.
- Flags never cleaned up; 90 flags, nobody knows what is live.
- Consent banner ignored by the analytics SDK initialised in `Application.onCreate`.

## Verification receipts

1. Tracking plan with event names, properties, and owners.
2. Identity merge test from anonymous to logged-in.
3. Flag inventory with lifecycle state and owner.
4. One experiment with exposure logging and a pre-registered metric.
5. Consent flow verified: no events before opt-in.

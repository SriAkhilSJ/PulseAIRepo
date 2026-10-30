---
name: push-notifications-architect
description: Architect-level push design — APNs and FCM mechanics, token lifecycle and refresh, notification payload rules, delivery guarantees and silent pushes, permission strategy, and the analytics that show whether a notification was ever useful. Use when the product relies on notifications to bring users back.
license: MIT
compatibility: APNs, FCM, OneSignal, Expo Push
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/devices-architect/push-notifications-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/usernotifications; firebase.google.com/docs/cloud-messaging; developer.android.com/develop/ui/views/notifications"
  crusor-triggers: "push notification, apns, fcm, notification token, silent push, notification permission, deep link notification, push delivery"
  crusor-verified-on: "2026-10-30"
---

# Push Notification Architect

Push is **best-effort delivery to a device you do not control**. Design for "may not
arrive", and never put state in the payload that is not also retrievable.

## When to use

- Time-sensitive information the user should see without opening the app.
- Re-engagement, transactional alerts, messaging.
- Background refresh via silent push.

## When NOT to use

- Critical data that must be delivered — use in-app sync plus a visible state.
- Anything a user cannot act on; notification fatigue is permanent.

## Decision 1 — Delivery

| Type | Guarantee |
|---|---|
| APNs alert | best effort, may be throttled/dropped |
| FCM | best effort, priority affects delivery |
| silent/data push | heavily rate-limited and may be dropped entirely |
| in-app message | guaranteed when the app is open |

- Never treat push as a message queue; deliver truth via your API and let the push be a
  hint.
- Collapse/thread by id so a burst does not produce twenty banners.
- Set TTLs so stale notifications do not arrive hours late.

## Decision 2 — Tokens

- Tokens change: register on every launch, send to your backend, and remove on logout.
- Store device + user association server-side; stale tokens must expire.
- Handle feedback endpoints (APNs 410, FCM errors) by pruning dead tokens.
- One user, many devices — send per device, not per user.

## Decision 3 — Payload

- Small payloads; APNs has a hard size limit and large payloads fail silently.
- Include ids for deep links, not full objects — fetch current state on open.
- Never put secrets or PII in the payload; it renders on the lock screen.
- Localise where the platform supports it, or send pre-localised text per device
  locale.

## Decision 4 — Permission

- Ask in context, after the user has seen value — not on first launch.
- Explain the benefit; use provisional/quiet permission where available.
- Track opt-in rate per prompt strategy; a low rate is a product problem, not a
  platform one.
- Respect the system settings; never nag with your own repeated prompts.

## Decision 5 — Measurement

- Delivery vs open vs action; a notification nobody opens is a cost.
- Per-campaign and per-user frequency caps; power-user spam is a churn driver.
- Quiet hours by time zone; sending at 3 a.m. local is a bug.
- A/B test timing and copy with a metric, not a hunch.

## Failure modes at scale

- Tokens never pruned; 40% of sends go to dead devices.
- Silent push used as the primary sync mechanism; Android throttles it away.
- Notification carries a stale price; user opens to a different number.
- Permission requested at launch; opt-in at 20%.
- Twenty notifications from one event because collapse keys were not set.

## Verification receipts

1. Delivery pipeline diagram: server → APNs/FCM → device, with TTLs.
2. Token lifecycle: registration, refresh, logout, and pruning.
3. Payload size and content review for secrets/PII.
4. Permission flow with measured opt-in rate.
5. Delivery/open/action metrics per campaign.

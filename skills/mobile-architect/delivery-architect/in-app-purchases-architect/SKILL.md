---
name: in-app-purchases-architect
description: Architect-level monetisation design — StoreKit/Play Billing product models, server-side receipt validation, subscription lifecycle and grace periods, restore purchases, entitlement modelling, and the store rules that decide what you can sell. Use when the app sells anything.
license: MIT
compatibility: StoreKit 2, Google Play Billing, RevenueCat, Stripe for web
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/delivery-architect/in-app-purchases-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/in-app-purchase; developer.android.com/google/play/billing; developer.apple.com/app-store/review/guidelines"
  crusor-triggers: "in app purchase, iap, subscription, storekit, play billing, receipt validation, entitlement, restore purchases, paywall"
  crusor-verified-on: "2026-10-30"
---

# In-App Purchases Architect

Purchases are **a server-side entitlement problem with a client that cannot be
trusted**. The store is the source of truth; your backend is the cache.

## When to use

- Subscriptions, one-off unlocks, or consumables.
- Entitlements must unlock features across devices.
- Revenue exists but receipt validation is client-side.

## When NOT to use

- Selling physical goods (store rules usually require another payment path).
- B2B invoicing where the store is not involved.

## Decision 1 — Product model

| Model | Notes |
|---|---|
| consumable | user buys repeatedly; must be finished/acknowledged |
| non-consumable | one-time unlock, restorable |
| auto-renewable subscription | lifecycle heavy: renewal, grace, billing retry |
| non-renewing subscription | you manage expiry |

- Model entitlements (what the user can do), not products — products change, features
  should not.
- Prices come from the store; do not hardcode in the app.

## Decision 2 — Validation

- Never trust the client: validate receipts/transactions server-side with the store's
  API.
- Server stores the entitlement with product id, expiry, and transaction id, keyed by
  account.
- Handle the App Store Server Notifications / Play RTDN webhooks for renewals,
  refunds, grace periods, and revocation.
- Idempotency: the same transaction id processed twice must not double-extend.

## Decision 3 — Client flow

- Purchase → validate server-side → unlock → finish transaction. Unlock only after
  server confirmation.
- Restore purchases prominently (store requirement) and on new-device login.
- Pending/deferred payments (Ask to Buy, SCA) need a state that resolves later.
- Offline: show cached entitlement with a "revalidating" state, never grant new
  purchases.

## Decision 4 — Subscription lifecycle

| State | UX |
|---|---|
| active | full access |
| grace period | access continues, warn |
| billing retry | limited access, prompt update |
| expired | revert to free, keep data |
| refunded/revoked | remove access, log reason |

- Test every state in the sandbox; the store's test tooling supports them.
- Downgrades/upgrades mid-cycle must not double-charge or lose time.

## Decision 5 — Rules and compliance

- Digital goods sold inside the app generally must use the store's payment system;
  know the current exceptions for your markets.
- Restore and "manage subscription" links are required.
- Refunds are the store's decision — do not promise otherwise.
- Tax handling is the store's; keep records for reconciliation.

## Failure modes at scale

- Client-side receipt check; jailbroken devices get free subscriptions.
- Webhooks not implemented; a cancellation keeps access until manual cleanup.
- Non-consumable not acknowledged; the user is charged again on reinstall.
- Entitlement tied to device, not account; upgrade loses purchases.
- Grace period unhandled; a payment hiccup locks out paying customers.

## Verification receipts

1. Product/entitlement map with what each grants.
2. Server-side validation demonstrated with a tampered receipt rejected.
3. Webhook test for renewal, cancellation, and refund.
4. Restore flow exercised on a fresh install.
5. Sandbox test across all subscription states.

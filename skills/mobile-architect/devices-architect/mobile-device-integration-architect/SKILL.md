---
name: mobile-device-integration-architect
description: Architect-level device capability integration — camera, location, Bluetooth, sensors, biometrics, and the permission model, background execution limits, and hardware variance that decide whether a feature works on real devices rather than on a simulator. Use when the app touches hardware.
license: MIT
compatibility: AVFoundation, CameraX, CoreLocation, CoreBluetooth, Android BLE
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/devices-architect/mobile-device-integration-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/avfoundation; developer.android.com/media/camera/camerax; developer.android.com/develop/connectivity/bluetooth"
  crusor-triggers: "camera, bluetooth, ble, location tracking, sensors, biometric, permissions model, nfc, hardware integration, background location"
  crusor-verified-on: "2026-10-30"
---

# Device Integration Architect

Hardware features fail on **permissions, backgrounding, and device variance** — never
on the happy path you tested in a simulator.

## When to use

- Camera capture, scanning, AR, NFC, BLE peripherals, sensors.
- Location, including background tracking.
- Biometric-gated actions.

## When NOT to use

- Server-side or UI-only features with no hardware dependency.

## Decision 1 — Permissions

| Permission | Reality |
|---|---|
| camera | prompt in context; denial must not break the app |
| location when-in-use | precise vs approximate choice |
| location always | requires justification, review scrutiny |
| bluetooth | two-stage on Android (scan + connect) |
| notifications | separate consent, ask later |

- Request at the moment of need with a one-line rationale.
- Handle denial, "don't ask again", and restricted states as first-class UI.
- Settings deep link for recovery; the app must stay usable without the permission.

## Decision 2 — Background reality

- iOS background execution is opportunistic; Android has Doze and background limits.
- Continuous location, BLE scanning, and audio require declared modes and justify
  battery/PR review.
- Design for "the OS paused me": checkpoint state, resume cleanly, never assume
  continuous execution.
- Geofencing and significant-change APIs over continuous polling where possible.

## Decision 3 — Hardware variance

- Camera: resolution, HDR, focus, frame rates differ; test the lowest-end supported
  device.
- BLE: vendor quirks are the norm — connection intervals, MTU sizes, reconnection
  behaviour.
- Sensors: availability and accuracy vary; always check availability before use.
- Simulators lie about all of the above; real devices only.

## Decision 4 — Data and privacy

- Media captured by the app is user data: storage location, retention, and deletion
  rules apply.
- Strip EXIF location unless the feature needs it.
- Do not upload full-resolution media by default; compress and cap size.
- Ship a privacy manifest/declaration for the capabilities you use.

## Decision 5 — Testing

- Matrix: oldest supported device, a mid-tier Android, and a flagship.
- Test permission denial, revocation mid-session, and low-battery/thermal states.
- Test with the app backgrounded mid-operation.
- Automated tests for logic; manual device passes for hardware.

## Failure modes at scale

- Camera works in the simulator's synthetic feed, breaks on a real device's rotation.
- BLE reconnection assumed; peripherals drop and the app hangs.
- Background location declared but the OS suspends it; tracking silently stops.
- Permission denied path shows a blank screen.
- Full-resolution photos uploaded over cellular; users uninstall.

## Verification receipts

1. Capability inventory with the permission and rationale for each.
2. Denial/revocation walkthrough for every permission.
3. Background behaviour tested on both platforms with the app killed.
4. Device matrix results, including the oldest supported device.
5. Media size, EXIF handling, and retention policy verified.

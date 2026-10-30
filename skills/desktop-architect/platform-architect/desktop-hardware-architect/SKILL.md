---
name: desktop-hardware-architect
description: Architect-level hardware integration from desktop apps — serial and USB devices, printers and scanners, barcode readers and kiosks, driver and permission reality per platform, and the failure handling a device-facing app needs when hardware misbehaves. Use when the app talks to physical equipment.
license: MIT
compatibility: Node serialport, libusb, CUPS/Windows printing, ESC/POS
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/platform-architect/desktop-hardware-architect
  crusor-origin: original
  crusor-sources: "serialport.io/docs; libusb.info; learn.microsoft.com/windows-hardware/drivers/print; openprinting.github.io/cups"
  crusor-triggers: "serial port, usb device, printer integration, receipt printer, barcode scanner, kiosk hardware, libusb, esc pos, hardware integration desktop"
  crusor-verified-on: "2026-10-30"
---

# Desktop Hardware Architect

Hardware integration is **an unreliable network with no retry semantics built in**.
Treat every device as a remote service that will disconnect mid-operation.

## When to use

- Serial/USB devices: scales, scanners, controllers, medical or industrial equipment.
- Printing, especially receipt and label printers.
- Kiosk deployments with peripheral sets.

## When NOT to use

- The "hardware" is a standard file or network protocol.
- A web app can reach the device through a vendor's cloud API.

## Decision 1 — Connection model

| Device | Approach |
|---|---|
| serial (RS-232/USB-serial) | `serialport`, explicit baud/parity/timeouts |
| USB HID | vendor SDK or hidraw with a documented protocol |
| printer | OS spooler (CUPS/WinSpool) or raw ESC/POS socket |
| scanner | TWAIN/WIA/ICA or the vendor's CLI |
| network device | TCP with heartbeat, not "connect once" |

- Device discovery at startup with a user-selectable list; never hardcode
  `/dev/ttyUSB0` or `COM3`.
- Keep the protocol documented in the repo — the vendor manual will be lost.

## Decision 2 — Reliability

- Reconnect with backoff on disconnect; surface state in the UI ("device offline").
- Timeouts on every read; a silent device must not hang the app.
- Queue outbound commands with ids and acknowledgements; devices do not implement
  retries.
- Handle partial writes and framing errors explicitly; serial data arrives in
  fragments.
- Idempotency matters for print jobs: a duplicate receipt is a real-world problem.

## Decision 3 — Platform reality

| Platform | Friction |
|---|---|
| Windows | COM ports, driver installs, spooler quirks |
| macOS | USB permissions, notarised kexts where relevant |
| Linux | udev rules, `dialout` group, Flatpak device access |

- Sandboxed packaging may block device access entirely — declare access explicitly
  (`--device` in Flatpak) or ship outside the sandbox.
- Antivirus/EDR can block raw device access; document the allowlist requirement.

## Decision 4 — Deployment and support

- Ship a diagnostics screen: detected devices, ports, firmware version, last error.
- Log device interactions (not payloads containing PII) for support.
- Version compatibility: firmware and app versions must be declared as a matrix.
- Field updates: how does a kiosk fleet get a fix at 2 a.m.?

## Decision 5 — Safety

- Physical actions (print, dispense, move) require confirmation for anything costly or
  irreversible.
- Fail safe: if the device is unresponsive mid-operation, leave the system in a known
  state.
- Never trust device input as validated data (scanned barcodes, scale readings).

## Failure modes at scale

- App hangs forever when the printer is switched off.
- Hardcoded port; works on the developer's machine, fails at the site.
- Duplicate label printed on retry; inventory counts drift.
- Flatpak sandbox without device access; nothing detected in production.
- Firmware update changes the protocol; no version check.

## Verification receipts

1. Device inventory with connection type and protocol documentation.
2. Disconnect/reconnect test mid-operation, with UI state shown.
3. Timeout and error handling demonstrated for each device class.
4. Permission and udev/sandbox configuration verified on a clean install.
5. Duplicate-operation test proving idempotency.

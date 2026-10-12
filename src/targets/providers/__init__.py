"""Target providers — one module per build target family.

* :mod:`~src.targets.providers.android` — Gradle + adb + emulator/device
* :mod:`~src.targets.providers.ios` — xcodebuild/simctl on macOS, pymobiledevice3 devices elsewhere
* :mod:`~src.targets.providers.desktop` — Electron, Tauri, Wails, Neutralino, .NET, Node shells
* :mod:`~src.targets.providers.web` — dev server + the existing browser pipeline
* :mod:`~src.targets.providers.flutter` / ``react_native`` — framework adapters that delegate
  to a platform provider for the actual device proof

Every provider implements :class:`~src.targets.providers.base.TargetProvider`:
``detect`` (is this workspace that target?), ``plan`` (ordered stages),
``interpret`` (evidence → receipt) and ``host_support`` (can this machine even
try?). Register a new one in :mod:`src.targets.registry`.
"""
from __future__ import annotations

from src.targets.providers.base import PlanUnavailable, TargetProvider

__all__ = ["PlanUnavailable", "TargetProvider"]

"""Crusor Preview — the device pane: a phone, tablet or emulator mirrored into the IDE.

The web preview answers "does the page render?" by framing a dev server with the
inspect overlay injected. A mobile app has no URL to frame, so this module gives
the same window something real to render: a **live screen** pulled from an
attached Android device, plus the input path that makes the mirror interactive.

How it is wired (``src/preview/server.py`` owns the socket work):

* ``POST /crusor-preview/device`` (``X-Crusor-Preview-Secret``) registers a pane
  and returns ``{token, paneUrl}``. The serial is resolved like every other
  device operation in this repo: explicit serial → the single attached ``device``.
* ``GET  /crusor-preview/device/<token>/``        the pane document (toolbar + mirror)
* ``GET  /crusor-preview/device/<token>/stream``  ``multipart/x-mixed-replace`` frames
* ``GET  /crusor-preview/device/<token>/frame``   one frame (PNG, screenshot fallback)
* ``GET  /crusor-preview/device/<token>/status``  JSON: serial, model, size, fps, viewers, last error
* ``POST /crusor-preview/device/<token>/input``   normalized tap/swipe/text/key/rotate
* ``POST /crusor-preview/device/<token>/release`` tear the pane down and close its streams

Three decisions worth keeping:

**Accessibility-free, dependency-light capture.** Frames come from
``adb exec-out screencap -p``. That is a few frames per second, not screen
casting: no scrcpy server, no H.264 decoder in a webview, no native dependency.
A mirror at 4 fps is enough to *watch the app*, and ``device_action`` still does
the precise driving.

**PNG whenever Pillow is missing.** Pillow is a declared dependency, so frames are
normally transcoded to JPEG (roughly a tenth of the bytes, which is what makes a
4 fps stream comfortable over the proxy). Without it the same multipart stream
carries PNG parts — browsers render both.

**Coordinates are normalized in the browser.** The pane posts ``x``/``y`` in
``0..1`` and the server multiplies by the real device size, so a pane scaled to a
window corner still taps the right pixel. Input args are built by the pure
:func:`input_commands`, which is the piece worth testing.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

__all__ = [
    "DEVICE_PATH",
    "DEVICE_PREFIX",
    "STREAM_BOUNDARY",
    "DevicePane",
    "DeviceRegistry",
    "adb_binary",
    "capture_frame",
    "clamp_fps",
    "connected_serials",
    "device_facts",
    "input_commands",
    "list_devices",
    "pane_document",
    "pick_serial",
    "run_adb",
]

#: Registration endpoint (POST, secret-guarded), mirroring ``/crusor-preview/target``.
DEVICE_PATH = "/crusor-preview/device"
#: Pane routes. The token in the path is the capability, exactly like ``/p/<token>/``.
DEVICE_PREFIX = "/crusor-preview/device/"

#: Boundary for the multipart frame stream. Fixed, not random: one pane streams to one browser,
#: and a stable boundary is one less thing to disagree about when reading a packet capture.
STREAM_BOUNDARY = "crusordevice"

_DEFAULT_FPS = 4.0
_MAX_FPS = 10.0
_MIN_FPS = 0.5
#: Concurrent frame streams across the whole proxy. Each stream is a real adb child every frame,
#: so this is a resource ceiling, not a tunable.
_MAX_STREAMS = 4
_STREAM_MAX_SECONDS = 6 * 60 * 60
_CAPTURE_TIMEOUT = 15.0
_FACTS_TTL = 30.0

_DEVICE_LINE = re.compile(
    r"^(?P<serial>\S+)\s+(?P<state>device|offline|unauthorized|bootloader|recovery|sideload)\b(?P<rest>.*)$"
)
_MODEL_FIELD = re.compile(r"\bmodel:(?P<model>\S+)")
_SIZE_FIELD = re.compile(r"Physical size:\s*(?P<w>\d+)x(?P<h>\d+)")

#: Named keys the pane may send. The numeric codes are the stable Android ones.
KEY_CODES: dict[str, str] = {
    "home": "3",
    "back": "4",
    "recents": "187",
    "app_switch": "187",
    "menu": "82",
    "enter": "66",
    "escape": "111",
    "delete": "67",
    "tab": "61",
    "space": "62",
    "power": "26",
    "volume_up": "24",
    "volume_down": "25",
    "volume_mute": "164",
    "wakeup": "224",
    "sleep": "223",
    "dpad_up": "19",
    "dpad_down": "20",
    "dpad_left": "21",
    "dpad_right": "22",
    "dpad_center": "23",
}

_PANE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #141414; color: #f1ece8;
    font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  body { display: flex; flex-direction: column; overflow: hidden; }
  .bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 8px 10px; background: #1f1f1f; border-bottom: 1px solid #2e2e2e; }
  body.bare .bar, body.bare .hint { display: none; }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 999px;
    background: #262626; border: 1px solid #333; font-size: 11.5px; white-space: nowrap; }
  .chip b { font-weight: 600; color: #fab283; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: #f5a97f; }
  .dot.live { background: #9ece6a; }
  .dot.down { background: #e06c75; }
  button { font: inherit; font-size: 12px; color: #f1ece8; background: #2a2a2a;
    border: 1px solid #3a3a3a; border-radius: 7px; padding: 4px 10px; cursor: pointer; }
  button:hover { background: #333; border-color: #4a4a4a; }
  button:active { transform: translateY(1px); }
  input[type=text] { flex: 1 1 160px; min-width: 120px; font: inherit; font-size: 12px;
    color: #f1ece8; background: #202020; border: 1px solid #3a3a3a; border-radius: 7px; padding: 5px 9px; }
  .stage { position: relative; flex: 1; display: flex; align-items: center; justify-content: center;
    padding: 12px; min-height: 0; background:
      linear-gradient(45deg, #1a1a1a 25%, transparent 25%, transparent 75%, #1a1a1a 75%) 0 0/22px 22px,
      linear-gradient(45deg, #1a1a1a 25%, transparent 25%, transparent 75%, #1a1a1a 75%) 11px 11px/22px 22px,
      #151515; }
  .screen { max-width: 100%; max-height: 100%; height: auto; border-radius: 10px;
    box-shadow: 0 8px 34px rgba(0,0,0,.55); background: #000; touch-action: none;
    cursor: crosshair; user-select: none; -webkit-user-drag: none; }
  .overlay { position: absolute; inset: 12px; display: none; align-items: center; justify-content: center;
    text-align: center; padding: 20px; border-radius: 10px; background: rgba(15,15,15,.92);
    border: 1px solid #3a2a2a; color: #f1ece8; }
  .overlay.show { display: flex; }
  .overlay .card { max-width: 460px; }
  .overlay h3 { margin: 0 0 6px; font-size: 14px; color: #e06c75; }
  .overlay p { margin: 4px 0; color: #b9b2ad; font-size: 12.5px; }
  .overlay code { background: #222; border: 1px solid #333; border-radius: 5px; padding: 1px 5px; }
  .hint { padding: 6px 10px; background: #1a1a1a; border-top: 1px solid #2a2a2a;
    color: #8f8880; font-size: 11.5px; }
</style>
</head>
<body>
  <div class="bar">
    <span class="chip"><span class="dot" id="dot"></span><b id="serial">__SERIAL__</b></span>
    <span class="chip" id="model">__MODEL__</span>
    <button id="home" title="KEYCODE_HOME">Home</button>
    <button id="back" title="KEYCODE_BACK">Back</button>
    <button id="recents" title="KEYCODE_APP_SWITCH">Recents</button>
    <button id="rotate" title="rotate the device">Rotate</button>
    <button id="shot" title="download the current frame">Frame</button>
    <button id="reload" title="restart the frame stream">Refresh</button>
    <input type="text" id="text" placeholder="type into the focused field, Enter to send">
    <button id="send">Send</button>
  </div>
  <div class="stage">
    <img class="screen" id="screen" alt="device screen" src="__BASE__/stream">
    <div class="overlay" id="overlay"><div class="card">
      <h3>The device pane cannot stream</h3>
      <p id="overlay-detail">No frame arrived from adb.</p>
      <p>Check that the emulator or device is still attached (<code>adb devices</code>) and that
      <code>adb</code> is on PATH (or <code>$CRUSORAI_ADB</code>).</p>
      <p><button id="retry">Try again</button></p>
    </div></div>
  </div>
  <div class="hint">Taps, swipes and text here are <b>real input</b> on __SERIAL__ — this pane is a mirror
    (a few frames per second), not screen casting. Use the agent's <code>device_action</code> for precise,
    repeatable driving.</div>
<script>
(function () {
  var BASE = "__BASE__";
  var doc = document;
  var screen = doc.getElementById('screen');
  var overlay = doc.getElementById('overlay');
  var detail = doc.getElementById('overlay-detail');
  var dot = doc.getElementById('dot');
  var state = { live: false, down: null, frames: 0 };

  function post(path, payload) {
    return fetch(BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .catch(function () { return {}; });
  }

  function streamUrl() {
    return BASE + '/stream?ts=' + Date.now();
  }

  function startStream() {
    overlay.classList.remove('show');
    screen.src = streamUrl();
  }

  screen.addEventListener('load', function () {
    state.frames += 1;
    if (!state.live) { state.live = true; dot.className = 'dot live'; }
  });
  screen.addEventListener('error', function () {
    state.live = false;
    dot.className = 'dot down';
    detail.textContent = 'No frame arrived from adb.';
    overlay.classList.add('show');
  });

  // Normalized coordinates: the pane scales, the device does not.
  function at(event) {
    var rect = screen.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))
    };
  }

  screen.addEventListener('pointerdown', function (event) {
    event.preventDefault();
    screen.setPointerCapture(event.pointerId);
    state.down = { point: at(event), at: Date.now() };
  });

  screen.addEventListener('pointerup', function (event) {
    event.preventDefault();
    var start = state.down;
    state.down = null;
    if (!start) { return; }
    var end = at(event);
    var dx = (end.x - start.point.x), dy = (end.y - start.point.y);
    var moved = Math.sqrt(dx * dx + dy * dy);
    if (moved < 0.012 && (Date.now() - start.at) < 600) {
      post('/input', { action: 'tap', x: end.x, y: end.y });
    } else {
      post('/input', {
        action: 'swipe', x: start.point.x, y: start.point.y, x2: end.x, y2: end.y,
        ms: Math.min(1500, Math.max(120, Date.now() - start.at))
      });
    }
  });

  function key(name) { post('/input', { action: 'key', key: name }); }
  doc.getElementById('home').onclick = function () { key('home'); };
  doc.getElementById('back').onclick = function () { key('back'); };
  doc.getElementById('recents').onclick = function () { key('recents'); };
  doc.getElementById('rotate').onclick = function () { post('/input', { action: 'rotate' }); };
  doc.getElementById('reload').onclick = startStream;
  doc.getElementById('retry').onclick = startStream;
  doc.getElementById('shot').onclick = function () {
    var a = doc.createElement('a');
    a.href = BASE + '/frame?ts=' + Date.now();
    a.download = '__SERIAL__-' + Date.now() + '.png';
    doc.body.appendChild(a); a.click(); doc.body.removeChild(a);
  };

  var text = doc.getElementById('text');
  function sendText() {
    if (!text.value) { return; }
    post('/input', { action: 'text', text: text.value }).then(function () { text.value = ''; });
  }
  doc.getElementById('send').onclick = sendText;
  text.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') { event.preventDefault(); sendText(); }
    if (event.key === 'Escape') { text.blur(); }
  });
  doc.addEventListener('keydown', function (event) {
    if (doc.activeElement === text) { return; }
    if (event.key === 'Escape') { key('back'); }
    if (event.key === 'Home') { key('home'); }
  });

  setInterval(function () {
    fetch(BASE + '/status', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var node = doc.getElementById('model');
        if (data && data.model) { node.textContent = data.model + '  ' + (data.width||0) + '×' + (data.height||0); }
        if (data && data.last_error && data.last_error !== '') {
          detail.textContent = data.last_error;
          overlay.classList.add('show');
        }
      })
      .catch(function () {});
  }, 3000);

  if (location.search.indexOf('bare=1') !== -1) { doc.body.classList.add('bare'); }
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# adb plumbing
# --------------------------------------------------------------------------- #

def adb_binary() -> str:
    """``$CRUSORAI_ADB`` → PATH. Same override convention as ``src/targets/toolchain.py``."""
    override = os.environ.get("CRUSORAI_ADB", "").strip()
    if override and Path(override).exists():
        return override
    return shutil.which("adb") or ""


def clamp_fps(value: Any, default: float = _DEFAULT_FPS) -> float:
    """Keep a requested frame rate inside what this backend can actually deliver."""
    try:
        rate = float(value)
    except (TypeError, ValueError):
        rate = default
    return max(_MIN_FPS, min(_MAX_FPS, rate))


def _run_text(argv: list[str], timeout: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:.0f}s: {' '.join(argv)}"
    except (OSError, FileNotFoundError) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")


def list_devices(adb: str = "") -> list[dict[str, str]]:
    """Every device ``adb`` reports, with its state and model. ``[]`` when adb is absent."""
    adb = adb or adb_binary()
    if not adb:
        return []
    code, output = _run_text([adb, "devices", "-l"], timeout=15)
    if code != 0:
        return []
    found: list[dict[str, str]] = []
    for line in output.splitlines():
        match = _DEVICE_LINE.match(line.strip())
        if not match:
            continue
        model = _MODEL_FIELD.search(match.group("rest"))
        found.append({
            "serial": match.group("serial"),
            "state": match.group("state"),
            "model": model.group("model") if model else "",
        })
    return found


def connected_serials(adb: str = "") -> list[str]:
    """Serials that are attached *and* ready for input (state ``device``)."""
    return [item["serial"] for item in list_devices(adb) if item["state"] == "device"]


def pick_serial(preferred: str = "", adb: str = "") -> str:
    """Explicit serial wins (a pane may be opened before the device finishes booting);
    otherwise the single attached device, else the first."""
    if preferred.strip():
        return preferred.strip()
    ready = connected_serials(adb)
    return ready[0] if ready else ""


def device_facts(serial: str, adb: str = "") -> dict[str, Any]:
    """Model and physical size — what the pane needs to scale normalized input."""
    adb = adb or adb_binary()
    facts: dict[str, Any] = {"model": "", "width": 0, "height": 0, "error": ""}
    if not adb or not serial:
        facts["error"] = "no adb or no serial"
        return facts
    code, model = _run_text([adb, "-s", serial, "shell", "getprop", "ro.product.model"], timeout=15)
    if code == 0:
        facts["model"] = model.strip().splitlines()[0].strip() if model.strip() else ""
    code, size = _run_text([adb, "-s", serial, "shell", "wm", "size"], timeout=15)
    if code == 0:
        match = _SIZE_FIELD.search(size)
        if match:
            facts["width"] = int(match.group("w"))
            facts["height"] = int(match.group("h"))
    if not facts["width"] or not facts["height"]:
        facts["error"] = "could not read the device size (wm size)"
    return facts


def _to_jpeg(png: bytes) -> bytes | None:
    """Best-effort PNG → JPEG. ``None`` means "keep the PNG"; never raises."""
    if os.environ.get("CRUSORAI_DEVICE_JPEG", "1").strip().lower() in {"0", "off", "false", "no"}:
        return None
    try:
        import io

        from PIL import Image  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        with Image.open(io.BytesIO(png)) as image:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=72, optimize=False)
            return buffer.getvalue()
    except Exception:
        return None


def capture_frame(serial: str, adb: str = "", *, jpeg: bool = True) -> tuple[bytes, str, str]:
    """One screen grab. Returns ``(bytes, content_type, error)``.

    ``exec-out`` (not ``shell``) so the PNG bytes come back un-mangled by a pty.
    """
    adb = adb or adb_binary()
    if not adb:
        return b"", "", "adb is not installed (or $CRUSORAI_ADB points nowhere)"
    if not serial:
        return b"", "", "no device attached — start an emulator or plug one in (adb devices)"
    try:
        proc = subprocess.run(
            [adb, "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=_CAPTURE_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return b"", "", f"screencap timed out after {_CAPTURE_TIMEOUT:.0f}s on {serial}"
    except (OSError, FileNotFoundError) as exc:
        return b"", "", str(exc)
    png = proc.stdout or b""
    if proc.returncode != 0 or not png:
        stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
        return b"", "", stderr or f"screencap exited {proc.returncode} on {serial}"
    if not png.startswith(b"\x89PNG"):
        # A shell that wrapped the binary in CRLF mangling produces exactly this, and it renders as
        # a broken image with no explanation anywhere. Say what happened instead.
        return b"", "", "screencap did not return a PNG (device still booting, or adb transport is off)"
    if jpeg:
        converted = _to_jpeg(png)
        if converted:
            return converted, "image/jpeg", ""
    return png, "image/png", ""


def run_adb(serial: str, argv: list[str], *, timeout: float = 30.0) -> tuple[int, str]:
    """Run one ``adb -s <serial> <argv>`` command. ``(code, output)``; never raises."""
    adb = adb_binary()
    if not adb:
        return 127, "adb is not installed (or $CRUSORAI_ADB points nowhere)"
    return _run_text([adb, "-s", serial, *argv], timeout)


def _escape_input_text(text: str) -> str:
    """``adb shell input text`` has no quoting layer we control: escape for the device shell.

    Spaces must become ``%s`` (a literal space ends the argument), and the shell
    metacharacters are backslash-escaped. Non-ASCII is not typeable this way —
    the caller gets the string back unchanged and Android drops what it cannot map.
    """
    escaped = []
    for char in text:
        if char == " ":
            escaped.append("%s")
        elif char == "\n":
            escaped.append(" ")
        elif char in "&|;<>()$`\\\"'*?[]#~!":
            escaped.append("\\" + char)
        else:
            escaped.append(char)
    return "".join(escaped)


def input_commands(
    payload: Any, *, width: int, height: int, serial: str = "",
) -> tuple[list[list[str]], str]:
    """Map a pane input payload to the ``adb`` argument lists that perform it.

    Pure on purpose: this is the part with a right answer, so it is unit-tested
    without a device. Returns ``(commands, error)`` where each command is the argv
    *after* ``adb -s <serial>``; an error means nothing should be run.
    """
    if not isinstance(payload, dict):
        return [], "input body must be a JSON object"
    action = str(payload.get("action") or "").strip().lower()
    if not action:
        return [], "input body needs an 'action'"

    if action in {"tap", "swipe"}:
        if not width or not height:
            return [], "the device size is unknown, so normalized coordinates cannot be mapped"
        try:
            x = float(payload.get("x", 0.0))
            y = float(payload.get("y", 0.0))
        except (TypeError, ValueError):
            return [], "x and y must be numbers in 0..1"
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return [], "x and y must be normalized to 0..1 (the pane maps them to device pixels)"
        px, py = int(round(x * width)), int(round(y * height))
        if action == "tap":
            return [["shell", "input", "tap", str(px), str(py)]], ""
        try:
            x2 = float(payload.get("x2", x))
            y2 = float(payload.get("y2", y))
        except (TypeError, ValueError):
            return [], "x2 and y2 must be numbers in 0..1"
        if not (0.0 <= x2 <= 1.0 and 0.0 <= y2 <= 1.0):
            return [], "x2 and y2 must be normalized to 0..1"
        try:
            duration = int(payload.get("ms", 300))
        except (TypeError, ValueError):
            duration = 300
        duration = max(50, min(4000, duration))
        return [[
            "shell", "input", "swipe", str(px), str(py),
            str(int(round(x2 * width))), str(int(round(y2 * height))), str(duration),
        ]], ""

    if action == "text":
        text = str(payload.get("text") or "")
        if not text:
            return [], "nothing to type"
        return [["shell", "input", "text", _escape_input_text(text)]], ""

    if action == "key":
        name = str(payload.get("key") or "").strip().lower()
        code = KEY_CODES.get(name) or (name if name.isdigit() else "")
        if not code:
            return [], f"unknown key {name!r}; known: {', '.join(sorted(KEY_CODES))}"
        return [["shell", "input", "keyevent", code]], ""

    if action == "rotate":
        try:
            degrees = int(payload.get("degrees", 0))
        except (TypeError, ValueError):
            degrees = 0
        rotation = (degrees // 90) % 4 if degrees else "next"
        if rotation == "next":
            return [
                ["shell", "settings", "put", "system", "accelerometer_rotation", "0"],
                ["shell", "input", "keyevent", "KEYCODE_DPAD_CENTER"],
                ["shell", "settings", "put", "system", "user_rotation", "1"],
            ], ""
        return [
            ["shell", "settings", "put", "system", "accelerometer_rotation", "0"],
            ["shell", "settings", "put", "system", "user_rotation", str(rotation)],
        ], ""

    return [], f"unknown action {action!r}; known: tap, swipe, text, key, rotate"


# --------------------------------------------------------------------------- #
# panes
# --------------------------------------------------------------------------- #

@dataclass
class DevicePane:
    """One registered device mirror."""

    token: str
    serial: str
    label: str
    created_at: float
    fps: float = _DEFAULT_FPS
    model: str = ""
    width: int = 0
    height: int = 0
    viewers: int = 0
    frames: int = 0
    bytes_out: int = 0
    last_error: str = ""
    facts_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def refresh_facts(self, adb: str = "", *, force: bool = False) -> None:
        """Re-read model/size at most every ``_FACTS_TTL`` seconds (a rotation changes the size)."""
        now = time.monotonic()
        if not force and (now - self.facts_at) < _FACTS_TTL and self.width and self.height:
            return
        facts = device_facts(self.serial, adb)
        self.model = facts.get("model") or self.model
        if facts.get("width") and facts.get("height"):
            self.width = int(facts["width"])
            self.height = int(facts["height"])
        self.facts_at = now

    def status(self) -> dict[str, Any]:
        return {
            "ok": not self.last_error,
            "token": self.token,
            "serial": self.serial,
            "label": self.label,
            "model": self.model,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "frames": self.frames,
            "viewers": self.viewers,
            "last_error": self.last_error,
            "pane_url": f"{DEVICE_PREFIX}{self.token}/",
        }


class DeviceRegistry:
    """The proxy's device panes. Owned by :class:`~src.preview.server.PreviewServer`."""

    def __init__(self) -> None:
        self._panes: dict[str, DevicePane] = {}
        self._lock = threading.Lock()

    def register(self, serial: str = "", *, label: str = "", fps: float = _DEFAULT_FPS) -> DevicePane:
        """Create a pane for ``serial`` (or the single attached device).

        Raises :class:`ValueError` when there is nothing to mirror — a pane that
        silently shows a black rectangle is worse than a refusal.
        """
        adb = adb_binary()
        if not adb:
            raise ValueError(
                "adb is not installed, so there is no device to mirror. Install Android platform-tools "
                "(or set $CRUSORAI_ADB), then try again."
            )
        resolved = pick_serial(serial, adb)
        if not resolved:
            attached = list_devices(adb)
            if attached:
                states = ", ".join(f"{item['serial']} ({item['state']})" for item in attached)
                raise ValueError(
                    f"no device is ready for input; attached: {states}. Start or authorize one first."
                )
            raise ValueError(
                "no Android device or emulator is attached (`adb devices` is empty). Start an "
                "emulator first — the agent's `verify_target_app` will boot one if needed."
            )
        pane = DevicePane(
            token=secrets.token_urlsafe(16),
            serial=resolved,
            label=label.strip() or resolved,
            created_at=time.time(),
            fps=clamp_fps(fps),
        )
        pane.refresh_facts(adb, force=True)
        with self._lock:
            self._panes[pane.token] = pane
        return pane

    def pane(self, token: str) -> DevicePane | None:
        with self._lock:
            return self._panes.get(token or "")

    def forget(self, token: str) -> bool:
        with self._lock:
            return self._panes.pop(token or "", None) is not None

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            panes = list(self._panes.values())
        return [pane.status() for pane in panes]

    def active_streams(self) -> int:
        with self._lock:
            return sum(1 for pane in self._panes.values() if pane.viewers > 0)


def stream_frames(pane: DevicePane, adb: str = "", *, limit: int = 0) -> Iterator[tuple[bytes, str]]:
    """Yield ``(frame_bytes, content_type)`` until the client goes away or ``limit`` frames land.

    ``limit=0`` means "until stopped". The caller owns the socket and stops iterating
    when a write fails; this generator only owns the cadence.
    """
    interval = 1.0 / max(_MIN_FPS, min(_MAX_FPS, pane.fps))
    emitted = 0
    while limit == 0 or emitted < limit:
        started = time.monotonic()
        body, content_type, error = capture_frame(pane.serial, adb)
        with pane.lock:
            if error:
                pane.last_error = error
            else:
                pane.last_error = ""
                pane.frames += 1
                pane.bytes_out += len(body)
        if not body:
            # Nothing to send: surface the reason through /status and let the pane show it.
            yield b"", ""
            if limit:
                return
        else:
            pane.refresh_facts(adb)
            yield body, content_type
            emitted += 1
        elapsed = time.monotonic() - started
        delay = interval - elapsed
        if delay > 0:
            time.sleep(delay)
    return


def pane_document(pane: DevicePane, *, bare: bool = False) -> str:
    """The pane HTML. Absolute URLs on purpose: the preview window frames a target through
    ``/p/<token>/``, and a relative URL there would be re-proxied instead of reaching the
    device route directly."""
    base = f"{DEVICE_PREFIX}{pane.token}"
    title = f"{pane.label} — device preview"
    model = pane.model or "unknown device"
    size = f"{pane.width}×{pane.height}" if pane.width and pane.height else "size unknown"
    document = (
        _PANE_TEMPLATE
        .replace("__TITLE__", title.replace("<", "&lt;"))
        .replace("__BASE__", base)
        .replace("__SERIAL__", (pane.serial or "no device").replace("<", "&lt;"))
        .replace("__MODEL__", f"{model}  {size}".replace("<", "&lt;"))
    )
    if bare:
        document = document.replace("<body>", '<body class="bare">', 1)
    return document

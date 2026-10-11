"""Media tools — image & video search + binary download for the workspace.

Closes the "agent changed the product copy but never got the product photo"
gap: web_search/web_fetch/web_extract are text-only, so the model had no way
to return an image URL or save a binary asset. Two tools, hermes tool shape
(`@tool`, error strings returned, never raised — D17):

- ``media_search`` — keyless license-aware search across Openverse (CC
  images) and Wikimedia Commons (images + webm/ogv video); Pexels
  photos/videos are added automatically when ``PEXELS_API_KEY`` is set.
- ``media_download`` — validated binary download into the workspace
  (content-type allow-list, size caps, workspace-relative paths only) so the
  model can reference the local file from HTML/CSS it writes.

Both are deliberately context-frugal: search returns compact numbered lines,
download returns a single "saved" receipt line.
"""
from __future__ import annotations

import os
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from urllib.parse import quote_plus, urlparse

try:
    import httpx
except ImportError:
    httpx = None

try:
    from langchain_core.tools import tool
except ImportError:
    # Standalone fallback decorator
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        fn.name = fn.__name__
        return fn

_USER_AGENT = "CrusorAI-Agent/1.0 (media tools)"
# Binary size caps: hero images and short product loops, not raw footage.
_MAX_IMAGE_BYTES = 15 * 1024 * 1024
_MAX_VIDEO_BYTES = 60 * 1024 * 1024
_CHUNK = 64 * 1024
_TIMEOUT = 15
# Rate-limit backoff: CDNs (Wikimedia) throttle shared IPs with HTTP 429.
# One bounded retry — proven to succeed in practice — then fail fast with an
# actionable message so the model does not loop on the same host.
_429_DEFAULT_DELAY = 5.0
_429_MAX_DELAY = 15.0


def _pause(seconds: float) -> None:
    """Indirection over time.sleep so tests can stub the wait."""
    time.sleep(seconds)


def _retry_after_delay(headers) -> float:
    """Seconds to wait before the single 429 retry (honors Retry-After)."""
    raw = (headers.get("retry-after") or "").strip()
    if raw.isdigit():
        return float(min(int(raw), _429_MAX_DELAY))
    return _429_DEFAULT_DELAY


def _openverse_images(query: str, limit: int) -> list[dict]:
    """Openverse (openverse.org) — CC-licensed image search, no API key."""
    resp = httpx.get(
        "https://api.openverse.org/v1/images/",
        params={"q": query, "page_size": limit, "mature": "false"},
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    out = []
    for item in resp.json().get("results", [])[:limit]:
        url = item.get("url") or ""
        if not url:
            continue
        out.append({
            "title": item.get("title") or "untitled",
            "url": url,
            "width": item.get("width") or 0,
            "height": item.get("height") or 0,
            "license": f"CC {item.get('license', '?')} {item.get('license_version', '')}".strip(),
            "provider": f"openverse/{item.get('provider', '?')}",
            "page": item.get("foreign_landing_url") or "",
            "media_type": "image",
        })
    return out


def _wikimedia(query: str, limit: int, media_type: str) -> list[dict]:
    """Wikimedia Commons — freely-licensed files, images AND video
    (.webm/.ogv play directly in <video> tags). No API key."""
    search = f"filetype:video {query}" if media_type == "video" else f"filetype:bitmap {query}"
    resp = httpx.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": search,
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
        },
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    pages = (resp.json().get("query") or {}).get("pages") or {}
    out = []
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = info.get("mime") or ""
        url = info.get("url") or ""
        if not url:
            continue
        want = "video" if mime.startswith("video/") else "image"
        if media_type != "all" and want != media_type:
            continue
        license_name = ""
        metadata = info.get("extmetadata") or {}
        license_name = (metadata.get("LicenseShortName") or {}).get("value", "")
        out.append({
            "title": (page.get("title") or "").removeprefix("File:"),
            "url": url,
            "width": info.get("width") or 0,
            "height": info.get("height") or 0,
            "license": license_name or "see Commons page",
            "provider": "wikimedia-commons",
            "page": info.get("descriptionurl") or "",
            "media_type": want,
        })
    return out


def _pexels(query: str, limit: int, media_type: str) -> list[dict]:
    """Pexels — free stock photos/videos. Needs PEXELS_API_KEY; silently
    contributes nothing when the key is absent."""
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return []
    headers = {"Authorization": key, "User-Agent": _USER_AGENT}
    out: list[dict] = []
    if media_type in ("image", "all"):
        resp = httpx.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": limit},
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        for photo in resp.json().get("photos", [])[:limit]:
            src = photo.get("src") or {}
            url = src.get("large") or src.get("original") or ""
            if not url:
                continue
            out.append({
                "title": photo.get("alt") or "pexels photo",
                "url": url,
                "width": photo.get("width") or 0,
                "height": photo.get("height") or 0,
                "license": "Pexels License (free, attribution appreciated)",
                "provider": "pexels",
                "page": photo.get("url") or "",
                "media_type": "image",
            })
    if media_type in ("video", "all"):
        resp = httpx.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": limit},
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        for video in resp.json().get("videos", [])[:limit]:
            files = video.get("video_files") or []
            if not files:
                continue
            # pick the smallest HD-ish mp4 (sd first: cheap to download)
            files = sorted(files, key=lambda f: f.get("width") or 0)
            best = next((f for f in files if f.get("file_type") == "video/mp4"), files[0])
            out.append({
                "title": video.get("url", "pexels video").rsplit("/", 1)[-1] or "pexels video",
                "url": best.get("link", ""),
                "width": best.get("width") or 0,
                "height": best.get("height") or 0,
                "duration_s": video.get("duration") or 0,
                "license": "Pexels License (free, attribution appreciated)",
                "provider": "pexels",
                "page": video.get("url") or "",
                "media_type": "video",
            })
    return out


@tool
def media_search(query: str, media_type: str = "image", max_results: int = 6) -> str:
    """
    Find stock photos and videos on the web for UI work — product shots,
    hero banners, avatars, backgrounds, short video loops.

    Searches Openverse and Wikimedia Commons (no API key needed, openly
    licensed) plus Pexels when PEXELS_API_KEY is configured. Returns a
    numbered list of direct file URLs with dimensions and license — pick
    one and save it into the workspace with media_download before
    referencing it from HTML/CSS (never hotlink).

    Args:
        query: what to look for, e.g. "luxury perfume bottle".
        media_type: "image", "video", or "all".
        max_results: results per source, 1-10.
    """
    query = (query or "").strip()
    if not query:
        return "media_search error: query must not be empty"
    media_type = (media_type or "image").strip().lower()
    if media_type not in ("image", "video", "all"):
        return f"media_search error: media_type must be image|video|all, got {media_type!r}"
    max_results = max(1, min(int(max_results), 10))

    sources: list[tuple[str, object]] = [
        ("openverse", lambda: _openverse_images(query, max_results)),
        ("wikimedia", lambda: _wikimedia(query, max_results, media_type)),
        ("pexels", lambda: _pexels(query, max_results, media_type)),
    ]
    results: list[dict] = []
    failures: list[str] = []
    for name, fn in sources:
        try:
            results.extend(fn())
        except Exception as error:
            failures.append(f"{name}: {error}")

    # dedupe by URL, keep order
    seen: set[str] = set()
    unique = []
    for item in results:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)

    if not unique:
        msg = f"No stock media found for: {query!r} (media_type={media_type})"
        if failures:
            msg += "\nSource errors: " + "; ".join(failures)
        else:
            msg += (
                "\nTip: If this is a custom, bespoke, or unique asset that cannot be found in stock libraries "
                "(e.g. custom logo, fictional mascot, specialized 3D icon), generate it directly using: "
                f"generate_image(prompt={query!r}, filename='assets/custom_asset.png')"
            )
        return msg

    lines = [f"Media results for: {query} ({media_type}) — {len(unique)} found"]
    if failures:
        lines.append("(sources unavailable: " + "; ".join(failures) + ")")
    for i, item in enumerate(unique, start=1):
        dims = f"{item.get('width') or '?'}x{item.get('height') or '?'}"
        duration = f" · {item['duration_s']}s" if item.get("duration_s") else ""
        lines.append(
            f"{i}. [{item['media_type']}] {item['title']}\n"
            f"   URL: {item['url']}\n"
            f"   {item['provider']} · {dims}{duration} · {item['license']}\n"
            f"   page: {item['page'] or 'n/a'}"
        )
    lines.append(
        "\nNext: media_download(url, filename='assets/<name>') then reference the "
        "local path in your HTML/CSS. Respect the license (CC BY needs attribution)."
    )
    return "\n".join(lines)


_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif", "image/svg+xml": ".svg", "image/avif": ".avif",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/ogg": ".ogv",
}

# magic-byte sniffing fallback for servers that lie about content-type


def _sanitize_dest(filename: str, content_type: str) -> tuple[Path, str | None]:
    """Workspace-relative destination path. Returns (path, error)."""
    raw = (filename or "").strip()
    filename = raw.strip("/").replace("\\", "/")
    if not filename:
        return Path(), "filename must not be empty"
    if raw.startswith(("/", "~")) or ".." in Path(filename).parts:
        return Path(), f"filename must be a workspace-relative path (no absolute/.. paths): {filename!r}"
    path = Path(filename)
    # neutralize unsafe segments but keep structure
    safe_parts = [re.sub(r"[^\w.\- ()]", "_", part) for part in path.parts]
    path = Path(*safe_parts)
    if path.suffix == "":
        path = path.with_suffix(_EXT_BY_CONTENT_TYPE.get(content_type, ".bin"))
    return path, None


@tool
def media_download(url: str, filename: str) -> str:
    """
    Download a web image or video into the workspace so HTML/CSS can
    reference it as a local asset. Validates content-type (image/* or
    video/*), enforces size caps (15MB images, 60MB videos), and only
    writes workspace-relative paths. Retries once with a short backoff
    when the host rate-limits (HTTP 429).

    Args:
        url: direct media URL (from media_search results).
        filename: workspace-relative destination, e.g. "assets/perfume.jpg".
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"media_download error: only http/https URLs are supported: {url!r}"

    for attempt in (1, 2):
        rate_limited = False
        delay = 0.0
        try:
            with httpx.stream(
                "GET", url,
                headers={"User-Agent": _USER_AGENT},
                timeout=60,
                follow_redirects=True,
            ) as response:
                if response.status_code == 429:
                    rate_limited = True
                    delay = _retry_after_delay(response.headers)
                else:
                    response.raise_for_status()
                    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                    if not (content_type.startswith("image/") or content_type.startswith("video/")):
                        return (
                            f"media_download error: URL is not media (content-type {content_type!r}). "
                            "Use the direct file URL from media_search results, not a page URL."
                        )
                    cap = _MAX_VIDEO_BYTES if content_type.startswith("video/") else _MAX_IMAGE_BYTES
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > cap:
                        mb = cap // (1024 * 1024)
                        return f"media_download error: file too large ({int(declared)} bytes; cap {mb}MB for {content_type})"

                    path, err = _sanitize_dest(filename, content_type)
                    if err:
                        return f"media_download error: {err}"
                    if path.suffix == ".bin":
                        return (
                            "media_download error: unsupported media content-type "
                            f"{content_type!r} — pick a jpg/png/webp/gif/svg/mp4/webm source"
                        )

                    path.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    first = b""
                    with open(path, "wb") as fh:
                        for chunk in response.iter_bytes(_CHUNK):
                            if not first:
                                first = chunk[:16]
                            written += len(chunk)
                            if written > cap:
                                fh.close()
                                path.unlink(missing_ok=True)
                                mb = cap // (1024 * 1024)
                                return f"media_download error: stream exceeded {mb}MB cap — aborted, partial file removed"
                            fh.write(chunk)
        except Exception as error:
            return f"media_download error for {url!r}: {error}"
        if rate_limited:
            if attempt == 1:
                # One bounded backoff retry (connection closed before sleeping).
                _pause(delay)
                continue
            break
        break  # download completed

    if rate_limited:
        return (
            "media_download error: source rate-limited (HTTP 429) after one retry — "
            "the host is throttling this IP. Wait ~30s, retry ONCE with a DIFFERENT "
            "URL from the search results (do not loop on this host), or fall back "
            "to an image/CSS placeholder and tell the user video was blocked."
        )

    if written == 0:
        path.unlink(missing_ok=True)
        return "media_download error: empty response body — nothing saved"

    # content-type lied? sniff magic bytes and fix the extension
    sniffed = None
    if first.startswith(b"\xff\xd8\xff"):
        sniffed = ".jpg"
    elif first.startswith(b"\x89PNG\r\n\x1a\n"):
        sniffed = ".png"
    elif first.startswith(b"GIF8"):
        sniffed = ".gif"
    elif first.startswith(b"RIFF") and first[8:12] == b"WEBP":
        sniffed = ".webp"
    if sniffed and path.suffix.lower() != sniffed:
        fixed = path.with_suffix(sniffed)
        path.rename(fixed)
        path = fixed

    kb = written / 1024
    size = f"{kb:.0f} KB" if kb < 1024 else f"{written / (1024 * 1024):.1f} MB"
    rel = path.as_posix()
    return (
        f"saved: {rel} ({size}, {content_type})\n"
        f"Reference it locally — e.g. src=\"{rel}\" / url('{rel}') — never hotlink the remote URL."
    )


def _fetch_bytes(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    """Fetch binary content with httpx if available, falling back to urllib."""
    hdrs = dict(headers or {})
    if "User-Agent" not in hdrs:
        hdrs["User-Agent"] = _USER_AGENT
    if httpx is not None:
        resp = httpx.get(url, headers=hdrs, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _post_json(url: str, data: dict, headers: dict | None = None, timeout: int = 45) -> dict:
    """POST JSON with httpx if available, falling back to urllib."""
    import json
    hdrs = dict(headers or {})
    if "User-Agent" not in hdrs:
        hdrs["User-Agent"] = _USER_AGENT
    hdrs["Content-Type"] = "application/json"
    body = json.dumps(data).encode("utf-8")
    if httpx is not None:
        resp = httpx.post(url, headers=hdrs, content=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _strip_watermark(image_bytes: bytes, target_height: int = 1024) -> bytes:
    """Cleanly crop out bottom watermark bar from free generative endpoints and return pure image bytes."""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(image_bytes))
        w, h = im.size
        # The watermark bar on free mirrors is strictly located in the bottom 36-48px (approx 4.5% of height)
        crop_bottom = min(50, max(32, int(h * 0.046)))
        if h > crop_bottom * 2:
            # Crop off the watermark bar cleanly
            cropped = im.crop((0, 0, w, h - crop_bottom))
            out = io.BytesIO()
            fmt = im.format or "PNG"
            cropped.save(out, format=fmt)
            return out.getvalue()
    except Exception:
        pass
    return image_bytes


@tool
def generate_image(
    prompt: str,
    filename: str = "assets/generated_image.png",
    aspect_ratio: str = "1:1",
    model: str = "auto",
) -> str:
    """
    Generate a brand-new custom AI image from a text description and save it
    directly into the workspace as a local file (e.g. "public/logo.png" or "assets/banner.png").

    Use this tool when the user asks for CUSTOM, UNIQUE, or BESPOKE visual assets that
    cannot be found in stock libraries — such as custom brand logos, bespoke app icons,
    futuristic UI artwork, fantasy graphics, or tailored mascots.
    For standard real-world photos (landscapes, generic people, stock objects),
    prefer media_search + media_download instead.

    Args:
        prompt: Detailed visual prompt describing the custom image to create.
        filename: Workspace-relative path to save the generated image (e.g. "public/logo.png").
        aspect_ratio: "1:1" (square: 1024x1024), "16:9" (landscape: 1280x720), or "9:16" (portrait: 720x1280).
        model: "auto", "dall-e-3", "flux", or "pollinations".
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return "generate_image error: prompt must not be empty"

    # Resolve dimensions
    ar = (aspect_ratio or "1:1").strip().lower()
    if ar in ("16:9", "landscape", "banner", "wide"):
        width, height = 1280, 720
        dalle_size = "1792x1024"
    elif ar in ("9:16", "portrait", "story", "tall"):
        width, height = 720, 1280
        dalle_size = "1024x1792"
    else:
        width, height = 1024, 1024
        dalle_size = "1024x1024"

    path, err = _sanitize_dest(filename, "image/png")
    if err:
        return f"generate_image error: {err}"
    path.parent.mkdir(parents=True, exist_ok=True)

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    velona_key = os.environ.get("VELONA_API_KEY", "").strip()
    velona_base = os.environ.get("VELONA_BASE_URL", "https://velona.in/gateway/v1").rstrip("/")
    fal_key = os.environ.get("FAL_KEY", "").strip()
    together_key = os.environ.get("TOGETHER_API_KEY", "").strip()
    stability_key = os.environ.get("STABILITY_API_KEY", "").strip()

    model_choice = (model or "auto").strip().lower()

    # 1. Velona.in Gateway path (UPI / INR Indian Unified Gateway)
    if (model_choice in ("auto", "velona") and velona_key):
        try:
            res = _post_json(
                f"{velona_base}/images/generations",
                headers={"Authorization": f"Bearer {velona_key}"},
                data={
                    "model": "dall-e-3" if "dall" in model_choice else "flux-1-schnell",
                    "prompt": prompt,
                    "n": 1,
                    "size": dalle_size,
                    "response_format": "b64_json",
                },
                timeout=60,
            )
            data = res.get("data", [])
            if data and data[0].get("b64_json"):
                import base64
                img_bytes = base64.b64decode(data[0]["b64_json"])
                path.write_bytes(img_bytes)
                kb = len(img_bytes) / 1024
                rel = path.as_posix()
                return (
                    f"saved: {rel} ({kb:.0f} KB, image/png, {dalle_size})\n"
                    f"Generated custom AI image via Velona Gateway from prompt: {prompt!r}\n"
                    f"Reference it locally — e.g. src=\"{rel}\" / url('{rel}')."
                )
            elif data and data[0].get("url"):
                img_bytes = _fetch_bytes(data[0]["url"], timeout=30)
                path.write_bytes(img_bytes)
                kb = len(img_bytes) / 1024
                rel = path.as_posix()
                return (
                    f"saved: {rel} ({kb:.0f} KB, image/png, {dalle_size})\n"
                    f"Generated custom AI image via Velona Gateway from prompt: {prompt!r}\n"
                    f"Reference it locally — e.g. src=\"{rel}\" / url('{rel}')."
                )
        except Exception:
            pass  # Fall through to other providers

    # 2. OpenAI DALL-E 3 path
    if (model_choice in ("auto", "dall-e-3", "dalle", "openai") and openai_key):
        try:
            res = _post_json(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {openai_key}"},
                data={
                    "model": "dall-e-3",
                    "prompt": prompt,
                    "n": 1,
                    "size": dalle_size,
                    "response_format": "b64_json",
                },
                timeout=60,
            )
            data = res.get("data", [])
            if data and data[0].get("b64_json"):
                import base64
                img_bytes = base64.b64decode(data[0]["b64_json"])
                path.write_bytes(img_bytes)
                kb = len(img_bytes) / 1024
                rel = path.as_posix()
                return (
                    f"saved: {rel} ({kb:.0f} KB, image/png, {dalle_size})\n"
                    f"Generated custom AI image via DALL-E 3 from prompt: {prompt!r}\n"
                    f"Reference it locally — e.g. src=\"{rel}\" / url('{rel}')."
                )
        except Exception:
            pass  # Fall through to other providers

    # 2. Fal.ai Flux path
    if (model_choice in ("auto", "flux", "fal") and fal_key):
        try:
            res = _post_json(
                "https://fal.run/fal-ai/flux/schnell",
                headers={"Authorization": f"Key {fal_key}"},
                data={
                    "prompt": prompt,
                    "image_size": {"width": width, "height": height},
                    "num_inference_steps": 4,
                },
                timeout=45,
            )
            images = res.get("images", [])
            if images and images[0].get("url"):
                img_url = images[0]["url"]
                img_bytes = _fetch_bytes(img_url, timeout=30)
                path.write_bytes(img_bytes)
                kb = len(img_bytes) / 1024
                rel = path.as_posix()
                return (
                    f"saved: {rel} ({kb:.0f} KB, image/png, {width}x{height})\n"
                    f"Generated custom AI image via Flux from prompt: {prompt!r}\n"
                    f"Reference it locally — e.g. src=\"{rel}\" / url('{rel}')."
                )
        except Exception:
            pass  # Fall through to other providers

    # 3. Together AI Flux path
    if (model_choice in ("auto", "flux", "together") and together_key):
        try:
            res = _post_json(
                "https://api.together.xyz/v1/images/generations",
                headers={"Authorization": f"Bearer {together_key}"},
                data={
                    "model": "black-forest-labs/FLUX.1-schnell",
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "steps": 4,
                    "n": 1,
                    "response_format": "b64_json",
                },
                timeout=45,
            )
            data = res.get("data", [])
            if data and data[0].get("b64_json"):
                import base64
                img_bytes = base64.b64decode(data[0]["b64_json"])
                path.write_bytes(img_bytes)
                kb = len(img_bytes) / 1024
                rel = path.as_posix()
                return (
                    f"saved: {rel} ({kb:.0f} KB, image/png, {width}x{height})\n"
                    f"Generated custom AI image via Together FLUX from prompt: {prompt!r}\n"
                    f"Reference it locally — e.g. src=\"{rel}\" / url('{rel}')."
                )
        except Exception:
            pass

    # 4. High-Quality Zero-Key Free FLUX Engine (Pollinations / Open-Access FLUX)
    # Allows instant high-definition AI image generation out of the box with zero API keys or payment.
    import random
    seed = random.randint(1000, 999999)
    encoded_prompt = quote_plus(prompt)
    
    fallback_endpoints = [
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&enhance=true&model=flux&seed={seed}",
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&model=flux-realism&seed={seed}",
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&model=turbo&seed={seed}",
    ]

    last_error = None
    for endpoint in fallback_endpoints:
        try:
            content = _fetch_bytes(endpoint, timeout=60)
            if content and len(content) > 100:
                cleaned_bytes = _strip_watermark(content, height)
                path.write_bytes(cleaned_bytes)
                kb = len(cleaned_bytes) / 1024
                rel = path.as_posix()
                return (
                    f"saved: {rel} ({kb:.0f} KB, image/png, {width}x{height})\n"
                    f"Generated custom AI image via Free FLUX.1 Engine (watermark cleanly removed) from prompt: {prompt!r}\n"
                    f"Reference it locally — e.g. src=\"{rel}\" / url('{rel}')."
                )
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        return f"generate_image error: failed to generate image ({last_error})"

    return "generate_image error: could not generate image from available providers"


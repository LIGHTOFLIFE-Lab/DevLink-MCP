# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Notice when a newer release exists, and say so.

Someone who downloaded an executable has no package manager to tell them a new
version came out. This asks GitHub once a day and shows a line in the settings
panel when there is something newer.

Three things it deliberately does not do:

*It does not download or replace anything.* The builds are unsigned; a program
that silently swaps its own executable for a file it fetched over the network is
a bad habit to build, and a worse one to ship. It shows the link and stops.

*It does not block anything.* The check runs on a background thread with a short
timeout, and the panel renders whether or not it finished. No network, a
firewall, GitHub being down — all of them look the same: no banner.

*It does not run without being asked twice.* It is off unless the build looks
like a downloaded one, and ``DEVLINK_NO_UPDATE_CHECK=1`` turns it off outright.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

RELEASES_API = "https://api.github.com/repos/LIGHTOFLIFE-Lab/DevLink-MCP/releases/latest"
RELEASES_PAGE = "https://github.com/LIGHTOFLIFE-Lab/DevLink-MCP/releases/latest"

CACHE_NAME = "update-check.json"
CACHE_SECONDS = 24 * 60 * 60
TIMEOUT_SECONDS = 4

__all__ = ["parse_version", "is_newer", "check", "start_background_check", "state"]


# --------------------------------------------------------------------------
# versions
# --------------------------------------------------------------------------

def parse_version(text: str) -> tuple:
    """``v1.2.3`` -> ``(1, 2, 3, 1)``. A pre-release sorts below its release.

    The trailing element is 0 for ``1.2.3-rc1`` and 1 for ``1.2.3``, so the
    plain release wins a comparison against its own pre-releases.
    """
    text = (text or "").strip().lstrip("vV")
    match = re.match(r"^(\d+(?:\.\d+)*)(.*)$", text)
    if not match:
        return ()
    numbers = tuple(int(part) for part in match.group(1).split("."))
    numbers = numbers + (0,) * (3 - len(numbers)) if len(numbers) < 3 else numbers
    suffix = match.group(2).strip()
    return numbers + (0 if suffix else 1,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    left, right = parse_version(candidate), parse_version(current)
    if not left or not right:
        return False
    return left > right


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

def _fetch(url: str = RELEASES_API, timeout: int = TIMEOUT_SECONDS) -> dict | None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"DevLink-MCP/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        # Offline, blocked, rate-limited, no releases yet — all the same to us.
        return None


def enabled() -> bool:
    if os.environ.get("DEVLINK_NO_UPDATE_CHECK", "").strip() not in ("", "0", "no", "false"):
        return False
    return True


def is_frozen_build() -> bool:
    """A downloaded executable, as opposed to a pip install or a checkout."""
    return bool(getattr(sys, "frozen", False))


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

def _cache_file(home: Path) -> Path:
    return Path(home) / "logs" / CACHE_NAME


def _read_cache(home: Path) -> dict | None:
    path = _cache_file(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - float(data.get("at", 0)) > CACHE_SECONDS:
        return None
    return data


def _write_cache(home: Path, data: dict) -> None:
    path = _cache_file(home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass          # a cache we cannot write is not worth an error


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------

def check(home: Path, force: bool = False, fetcher=_fetch) -> dict:
    """Return ``{"current", "latest", "newer", "url"}``.

    ``newer`` is False whenever we do not positively know otherwise.
    """
    result = {"current": __version__, "latest": "", "newer": False, "url": RELEASES_PAGE}

    if not enabled():
        return result

    if not force:
        cached = _read_cache(home)
        if cached is not None:
            result.update({k: cached.get(k, result[k]) for k in ("latest", "newer")})
            return result

    payload = fetcher()
    if not payload:
        # Remember the failure too, so a machine with no network does not make
        # a doomed request every time the panel is opened.
        _write_cache(home, {"at": time.time(), "latest": "", "newer": False})
        return result

    latest = str(payload.get("tag_name") or payload.get("name") or "")
    newer = is_newer(latest)
    result["latest"] = latest
    result["newer"] = newer
    if payload.get("html_url"):
        result["url"] = payload["html_url"]
    _write_cache(home, {"at": time.time(), "latest": latest, "newer": newer})
    return result


_state: dict = {}
_lock = threading.Lock()


def state() -> dict:
    with _lock:
        return dict(_state)


def start_background_check(home: Path) -> None:
    """Kick off a check that nothing waits for."""
    if not enabled():
        return

    def run() -> None:
        try:
            found = check(Path(home))
        except Exception:                          # noqa: BLE001 - never fatal
            return
        with _lock:
            _state.update(found)

    threading.Thread(target=run, daemon=True).start()

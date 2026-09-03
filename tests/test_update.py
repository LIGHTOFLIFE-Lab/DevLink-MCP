# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""The update check. No test here touches the network."""

from __future__ import annotations

import json
import time

import pytest

from devlink_mcp import update


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("DEVLINK_NO_UPDATE_CHECK", raising=False)


@pytest.fixture
def home(tmp_path):
    (tmp_path / "logs").mkdir(parents=True)
    return tmp_path


# --------------------------------------------------------------------------
# version comparison
# --------------------------------------------------------------------------

@pytest.mark.parametrize("candidate, current, expected", [
    ("v0.2.0", "0.1.0", True),
    ("0.2.0",  "0.1.0", True),
    ("v0.1.1", "0.1.0", True),
    ("v1.0.0", "0.9.9", True),
    ("v0.1.0", "0.1.0", False),
    ("v0.0.9", "0.1.0", False),
    ("v0.1.0", "0.2.0", False),
    # A pre-release is older than the release it leads to.
    ("v0.2.0-rc1", "0.2.0", False),
    ("v0.2.0", "0.2.0-rc1", True),
    # Junk must never read as "newer".
    ("", "0.1.0", False),
    ("not-a-version", "0.1.0", False),
    ("v", "0.1.0", False),
])
def test_version_comparison(candidate, current, expected):
    assert update.is_newer(candidate, current) is expected


def test_short_versions_are_padded():
    assert update.parse_version("v1.2")[:3] == (1, 2, 0)
    assert update.is_newer("v1.3", "1.2.9") is True


# --------------------------------------------------------------------------
# the check itself
# --------------------------------------------------------------------------

def test_reports_a_newer_release(home):
    payload = {"tag_name": "v9.9.9", "html_url": "https://example.invalid/r/9.9.9"}
    result = update.check(home, fetcher=lambda: payload)

    assert result["newer"] is True
    assert result["latest"] == "v9.9.9"
    assert result["url"] == "https://example.invalid/r/9.9.9"


def test_same_version_is_not_newer(home):
    result = update.check(home, fetcher=lambda: {"tag_name": f"v{update.__version__}"})
    assert result["newer"] is False


def test_network_failure_is_silent(home):
    """No network must look like no update, never like an error."""
    result = update.check(home, fetcher=lambda: None)
    assert result["newer"] is False
    assert result["latest"] == ""
    assert result["current"] == update.__version__


def test_a_failed_check_is_still_cached(home):
    """A machine with no network should not retry on every single launch."""
    update.check(home, fetcher=lambda: None)
    cache = json.loads((home / "logs" / update.CACHE_NAME).read_text(encoding="utf-8"))
    assert cache["newer"] is False


def test_result_is_cached(home):
    calls = []

    def fetcher():
        calls.append(1)
        return {"tag_name": "v9.9.9"}

    update.check(home, fetcher=fetcher)
    update.check(home, fetcher=fetcher)
    update.check(home, fetcher=fetcher)
    assert len(calls) == 1, "the cache was not used"


def test_force_bypasses_the_cache(home):
    calls = []

    def fetcher():
        calls.append(1)
        return {"tag_name": "v9.9.9"}

    update.check(home, fetcher=fetcher)
    update.check(home, force=True, fetcher=fetcher)
    assert len(calls) == 2


def test_stale_cache_is_refetched(home):
    stale = {"at": time.time() - update.CACHE_SECONDS - 10, "latest": "v0.0.1", "newer": False}
    (home / "logs" / update.CACHE_NAME).write_text(json.dumps(stale), encoding="utf-8")

    result = update.check(home, fetcher=lambda: {"tag_name": "v9.9.9"})
    assert result["newer"] is True


def test_corrupt_cache_is_ignored(home):
    (home / "logs" / update.CACHE_NAME).write_text("{ not json", encoding="utf-8")
    result = update.check(home, fetcher=lambda: {"tag_name": "v9.9.9"})
    assert result["newer"] is True


def test_unwritable_cache_does_not_raise(tmp_path):
    # logs/ deliberately absent and the path made unusable
    (tmp_path / "logs").write_text("i am a file, not a directory", encoding="utf-8")
    result = update.check(tmp_path, fetcher=lambda: {"tag_name": "v9.9.9"})
    assert result["newer"] is True


# --------------------------------------------------------------------------
# opting out
# --------------------------------------------------------------------------

def test_env_var_disables_the_check(home, monkeypatch):
    monkeypatch.setenv("DEVLINK_NO_UPDATE_CHECK", "1")
    calls = []
    result = update.check(home, fetcher=lambda: calls.append(1) or {"tag_name": "v9.9.9"})
    assert calls == [], "a disabled check still called out"
    assert result["newer"] is False


@pytest.mark.parametrize("value, still_enabled", [
    ("1", False), ("yes", False), ("true", False),
    ("0", True), ("no", True), ("false", True), ("", True),
])
def test_disable_flag_values(monkeypatch, value, still_enabled):
    monkeypatch.setenv("DEVLINK_NO_UPDATE_CHECK", value)
    assert update.enabled() is still_enabled


def test_background_check_never_raises(home, monkeypatch):
    def explode():
        raise RuntimeError("the network is on fire")

    monkeypatch.setattr(update, "_fetch", explode)
    update.start_background_check(home)      # must not propagate
    time.sleep(0.2)
    assert update.state().get("newer") in (None, False)

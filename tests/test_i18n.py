# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Language selection and catalogue completeness."""

from __future__ import annotations

import pytest

from devlink_mcp import i18n


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("DEVLINK_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("value, expected", [
    ("ko", "ko"), ("ko_KR", "ko"), ("ko_KR.UTF-8", "ko"),
    ("en", "en"), ("en_US.UTF-8", "en"),
    ("fr_FR.UTF-8", "en"),          # unknown language falls back
])
def test_locale_environment_is_honoured(monkeypatch, value, expected):
    monkeypatch.setenv("LANG", value)
    assert i18n.detect() == expected


@pytest.mark.parametrize("value", ["C", "POSIX", "C.UTF-8", ""])
def test_c_locale_means_no_preference(monkeypatch, value):
    """"C" is not a request for English, it is the absence of a request."""
    monkeypatch.setenv("LANG", value)
    assert i18n.detect() == "en"


def test_explicit_setting_beats_the_locale(monkeypatch):
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    monkeypatch.setenv("DEVLINK_LANG", "en")
    assert i18n.detect() == "en"


def test_argument_beats_everything(monkeypatch):
    monkeypatch.setenv("DEVLINK_LANG", "en")
    assert i18n.detect("ko") == "ko"


def test_lc_all_wins_over_lang(monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "ko_KR.UTF-8")
    assert i18n.detect() == "ko"


def test_unknown_key_returns_itself():
    assert i18n.t("no.such.key") == "no.such.key"


def test_missing_placeholder_does_not_raise():
    i18n.set_language("en")
    assert i18n.t("cfg.missing_fields")          # no kwargs supplied


def test_korean_catalogue_covers_english():
    missing = set(i18n.MESSAGES["en"]) - set(i18n.MESSAGES["ko"])
    assert missing == set(), f"untranslated: {sorted(missing)}"


def test_catalogue_is_english_filled():
    merged = i18n.catalogue("ko")
    assert set(merged) == set(i18n.MESSAGES["en"])

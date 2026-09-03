# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json

import pytest

from devlink_mcp import config
from devlink_mcp.config import Paths


def write_ini(tmp_path, text: str) -> Paths:
    paths = Paths(tmp_path)
    paths.ensure()
    paths.ini.write_text(text, encoding="utf-8")
    return paths


BASE = """
[DEFAULT]
port = 22
mode = exec
backup = /srv/backup

[alpha]
host = 10.0.0.1
user = root
password = s3cret
remote = /var/www/html
"""


def test_minimal_config_converts(tmp_path):
    paths = write_ini(tmp_path, BASE)
    result = config.generate(paths)

    assert result["ok"] is True
    entry = result["servers"]["alpha"]
    assert entry["host"] == "10.0.0.1"
    assert entry["port"] == 22
    assert entry["password"] == "s3cret"
    # safety rails are added without the user asking
    assert entry["commandBlacklist"]
    assert entry["allowedRemotePaths"] == ["/var/www/html", "/srv/backup"]
    assert entry["maxOutputBytes"] > 0


def test_outputs_are_written(tmp_path):
    paths = write_ini(tmp_path, BASE)
    config.generate(paths)

    mcp = json.loads(paths.mcp_json.read_text(encoding="utf-8"))
    sites = json.loads(paths.sites_json.read_text(encoding="utf-8"))
    assert "alpha" in mcp
    assert sites["alpha"]["remote"] == "/var/www/html"
    assert sites["alpha"]["exclude"]


def test_password_with_special_characters_survives(tmp_path):
    paths = write_ini(tmp_path, BASE.replace("s3cret", "p@ss%word,with=stuff"))
    result = config.generate(paths)
    assert result["servers"]["alpha"]["password"] == "p@ss%word,with=stuff"


def test_non_ascii_section_name(tmp_path):
    paths = write_ini(tmp_path, BASE.replace("[alpha]", "[서울-웹서버]"))
    result = config.generate(paths)
    assert "서울-웹서버" in result["servers"]


def test_one_bad_section_does_not_sink_the_rest(tmp_path):
    paths = write_ini(tmp_path, BASE + """
[broken]
host = 10.0.0.2
user = root
remote = not-absolute
""")
    result = config.generate(paths)

    assert "alpha" in result["servers"], "a valid server was dropped"
    assert "broken" not in result["servers"]
    assert any("broken" in e for e in result["errors"])


def test_placeholder_password_is_rejected(tmp_path):
    paths = write_ini(tmp_path, BASE.replace("s3cret", "CHANGE_ME"))
    result = config.generate(paths)
    assert not result["servers"]
    assert result["errors"]


def test_missing_auth_is_rejected(tmp_path):
    paths = write_ini(tmp_path, """
[alpha]
host = 10.0.0.1
user = root
remote = /var/www
""")
    result = config.generate(paths)
    assert result["errors"]


def test_disabled_section_is_skipped(tmp_path):
    paths = write_ini(tmp_path, BASE + """
[beta]
enabled = no
host = 10.0.0.3
user = root
password = x
remote = /var/www
""")
    result = config.generate(paths)
    assert "beta" not in result["servers"]
    assert result["skipped"]


def test_shell_mode_warns_about_transfers(tmp_path):
    paths = write_ini(tmp_path, BASE + """
[gamma]
host = 10.0.0.4
user = ops
password = x
remote = /srv/app
mode = shell
""")
    result = config.generate(paths)
    entry = result["servers"]["gamma"]
    assert entry["transportMode"] == "shell"
    assert any("gamma" in w for w in result["warnings"])


def test_allow_list_disables_the_warning(tmp_path):
    paths = write_ini(tmp_path, BASE + "allow = ^ls( .*)?|^cat .*\n")
    result = config.generate(paths)
    entry = result["servers"]["alpha"]
    assert entry["commandWhitelist"] == ["^ls( .*)?", "^cat .*"]


def test_duplicate_names_are_reported(tmp_path):
    paths = write_ini(tmp_path, BASE + """
[second]
name = alpha
host = 10.0.0.9
user = root
password = y
remote = /var/www
""")
    result = config.generate(paths)
    assert any("alpha" in e for e in result["errors"])


def test_unreadable_file_is_reported_not_raised(tmp_path):
    import os
    import sys

    paths = write_ini(tmp_path, BASE)
    if sys.platform.startswith("win"):
        pytest.skip("POSIX permission bits only")
    os.chmod(paths.ini, 0o000)
    try:
        problem = config.problem_with(paths.ini)
        assert problem
        result = config.generate(paths)
        assert result["ok"] is False
        assert result["errors"]
    finally:
        os.chmod(paths.ini, 0o600)


def test_paths_discovery_prefers_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVLINK_HOME", str(tmp_path / "custom"))
    assert Paths.discover().root == (tmp_path / "custom").resolve()
    assert Paths.discover(tmp_path / "explicit").root == (tmp_path / "explicit").resolve()

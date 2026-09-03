# Copyright 2026 sshpier contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from sshpier import cli
from sshpier.config import Paths


def test_init_creates_layout_and_a_config(tmp_path, capsys):
    home = tmp_path / "home"
    assert cli.main(["init", "--home", str(home)]) == 0

    paths = Paths(home)
    for directory in (paths.config_dir, paths.keys, paths.sites, paths.repos, paths.logs):
        assert directory.is_dir()
    assert paths.ini.exists(), "init produced no servers.ini"
    assert "[DEFAULT]" in paths.ini.read_text(encoding="utf-8")


def test_init_does_not_overwrite_an_existing_config(tmp_path):
    home = tmp_path / "home"
    cli.main(["init", "--home", str(home)])
    paths = Paths(home)
    paths.ini.write_text("[mine]\nhost = 1.1.1.1\n", encoding="utf-8")

    cli.main(["init", "--home", str(home)])
    assert paths.ini.read_text(encoding="utf-8") == "[mine]\nhost = 1.1.1.1\n"


def test_example_config_is_always_available():
    text = cli.example_config()
    assert "[DEFAULT]" in text


def test_check_reports_failure_with_a_nonzero_exit(tmp_path):
    home = tmp_path / "home"
    paths = Paths(home)
    paths.ensure()
    paths.ini.write_text("[bad]\nhost = 1.1.1.1\nuser = root\nremote = nope\n",
                         encoding="utf-8")
    assert cli.main(["check", "--home", str(home)]) == 1


def test_check_passes_on_a_good_config(tmp_path):
    home = tmp_path / "home"
    paths = Paths(home)
    paths.ensure()
    paths.ini.write_text(
        "[web]\nhost = 1.1.1.1\nuser = root\npassword = s3cret\nremote = /var/www\n",
        encoding="utf-8")
    assert cli.main(["check", "--home", str(home)]) == 0
    assert not paths.mcp_json.exists(), "check should not write anything"


def test_build_writes_the_mcp_config(tmp_path):
    home = tmp_path / "home"
    paths = Paths(home)
    paths.ensure()
    paths.ini.write_text(
        "[web]\nhost = 1.1.1.1\nuser = root\npassword = s3cret\nremote = /var/www\n",
        encoding="utf-8")
    assert cli.main(["build", "--home", str(home)]) == 0
    assert paths.mcp_json.exists()
    assert paths.sites_json.exists()


def test_language_flag_switches_messages(tmp_path, capsys):
    home = tmp_path / "home"
    paths = Paths(home)
    paths.ensure()
    # A password is present so that the *remote path* rule is what fails;
    # otherwise the missing-auth rule fires first and we compare the wrong message.
    paths.ini.write_text(
        "[bad]\nhost = 1.1.1.1\nuser = root\npassword = s3cret\nremote = nope\n",
        encoding="utf-8")

    cli.main(["check", "--home", str(home), "--lang", "ko"])
    korean = capsys.readouterr().err

    cli.main(["check", "--home", str(home), "--lang", "en"])
    english = capsys.readouterr().err

    assert korean != english
    assert "absolute path" in english


def test_unknown_site_is_reported_not_raised(tmp_path):
    home = tmp_path / "home"
    paths = Paths(home)
    paths.ensure()
    paths.ini.write_text(
        "[web]\nhost = 1.1.1.1\nuser = root\npassword = s3cret\nremote = /var/www\n",
        encoding="utf-8")
    assert cli.main(["status", "nosuch", "--home", str(home)]) == 1

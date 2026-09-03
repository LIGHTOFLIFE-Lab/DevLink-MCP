# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""The entry point the .dmg and .exe builds run.

Two behaviours are worth pinning down, because both are invisible from a
source checkout and only bite someone who downloaded a binary: the bare launch
has to create the layout before opening the panel, and a launch *with*
arguments has to behave like the ordinary command line, since that is how the
MCP client starts ``serve``.
"""
from __future__ import annotations

from devlink_mcp import desktop
from devlink_mcp.config import Paths


def test_arguments_are_passed_through_to_the_cli(tmp_path):
    home = tmp_path / "home"
    assert desktop.main(["init", "--home", str(home)]) == 0
    assert Paths(home).ini.exists()


def test_bare_launch_initialises_then_opens_the_panel(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("DEVLINK_HOME", str(home))
    monkeypatch.setattr("sys.argv", ["DevLink"])

    seen: list[list[str]] = []

    from devlink_mcp import cli

    real_cli_main = cli.main

    def fake_main(argv=None):
        seen.append(list(argv or []))
        if argv and argv[0] == "init":
            return real_cli_main(["init", "--home", str(home)])
        return 0  # stand in for the panel, which would otherwise block

    monkeypatch.setattr(cli, "main", fake_main)
    assert desktop.main() == 0
    assert seen == [["init"], ["gui"]], "the panel must be preceded by init"
    assert Paths(home).ini.exists()


def test_a_failing_panel_is_reported_rather_than_silent(tmp_path, monkeypatch):
    """A windowed build has no console, so failures must reach a dialog."""
    monkeypatch.setenv("DEVLINK_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("sys.argv", ["DevLink"])

    from devlink_mcp import cli

    def fake_main(argv=None):
        if argv and argv[0] == "init":
            return 0
        raise RuntimeError("port already in use")

    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "main", fake_main)
    monkeypatch.setattr(desktop, "_alert", lambda t, m: alerts.append((t, m)))

    assert desktop.main() == 1
    assert alerts and "port already in use" in alerts[0][1]

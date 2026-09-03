# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Turn parsed WinSCP sessions into a ``servers.ini`` file."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import DEFAULT_EXCLUDE
from .i18n import t

HEADER = """; devlink servers
;
; This file holds passwords. Keep it out of version control.
; Generated {when}

[DEFAULT]
port    = 22
mode    = exec
exclude = {exclude}
backup  = /var/backup/devlink
"""


def render(sessions: list[dict]) -> tuple[str, int, list[str]]:
    """Render an ini body. Returns (text, usable count, notes)."""
    lines = [HEADER.format(when=datetime.now().strftime("%Y-%m-%d %H:%M"),
                           exclude=", ".join(DEFAULT_EXCLUDE))]
    notes: list[str] = []
    seen: set[str] = set()
    count = 0

    for session in sessions:
        if not session.get("usable"):
            if not session.get("host"):
                notes.append(t("import.skip_nohost", name=session["name"]))
            else:
                notes.append(t("import.skip_proto", name=session["name"],
                               proto=session.get("protocol", "?")))
            continue

        name = session["name"]
        base, n = name, 2
        while name in seen:
            name, n = f"{base}-{n}", n + 1
        seen.add(name)

        block = [f"\n[{name}]", f"host     = {session['host']}"]
        if str(session.get("port", "22")) != "22":
            block.append(f"port     = {session['port']}")
        block.append(f"user     = {session.get('user', '')}")

        if session.get("key"):
            block.append(f"key      = {session['key']}")
            if session["key"].lower().endswith(".ppk"):
                notes.append(t("cfg.ppk", name=name))
        else:
            block.append(f"password = {session.get('password', '')}")
            if session.get("password_failed"):
                notes.append(t("import.result_failed", count=1) + f" [{name}]")

        block.append("remote   = ")
        if session.get("proxy"):
            block.append(f"proxy    = {session['proxy']}")

        lines.append("\n".join(block) + "\n")
        count += 1

    return "".join(lines), count, notes


def write_servers_ini(target: Path, sessions: list[dict]) -> tuple[int, list[str]]:
    text, count, notes = render(sessions)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return count, notes

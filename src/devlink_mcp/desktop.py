# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""What the double-clickable builds run.

The packaged application is the same program as ``devlink gui``; the only
difference is what happens around it. Someone who downloaded a .dmg or an .exe
has no terminal open, so this module does the two things a first-time user
would otherwise have to know to do — create the directory layout, then open the
settings panel — and, if something goes wrong, puts the reason in a window
instead of a stream nobody is watching.
"""

from __future__ import annotations

import os
import sys
import traceback


def _alert(title: str, message: str) -> None:
    """Show a message where a windowed build has no console to print to."""
    try:
        if sys.platform == "darwin":
            import subprocess

            script = (
                'display dialog {msg} with title {title} '
                "buttons {\"OK\"} default button 1 with icon caution"
            ).format(msg=_as_applescript(message), title=_as_applescript(title))
            subprocess.run(["osascript", "-e", script], check=False)
            return
        if os.name == "nt":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
    except Exception:  # pragma: no cover - the fallback below still reports it
        pass
    print(f"{title}: {message}", file=sys.stderr)


def _as_applescript(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main(argv: list[str] | None = None) -> int:
    """Prepare the layout, then hand over to the settings panel.

    With arguments, behave like the ``devlink`` command instead. The MCP client
    is registered with a command line of ``<this executable> serve --home …``
    (see ``gui.launcher_command``), so for someone who installed from a .dmg or
    an .exe this file *is* the CLI, and swallowing its arguments would leave
    them with a panel they cannot connect an assistant to.
    """
    from . import cli

    args = sys.argv[1:] if argv is None else argv
    if args:
        return cli.main(args)

    try:
        cli.main(["init"])
    except SystemExit:
        raise
    except Exception:
        _alert(
            "DevLink-MCP",
            "Could not create the settings directory.\n\n" + traceback.format_exc(limit=3),
        )
        return 1

    try:
        return cli.main(["gui"])
    except KeyboardInterrupt:
        return 0
    except SystemExit as exc:  # argparse and friends
        return int(exc.code or 0)
    except Exception:
        _alert(
            "DevLink-MCP",
            "The settings panel stopped unexpectedly.\n\n" + traceback.format_exc(limit=5),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

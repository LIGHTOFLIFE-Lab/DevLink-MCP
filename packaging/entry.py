# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Entry point for the frozen builds.

Someone who downloads a binary and double-clicks it has not typed a subcommand,
and would otherwise get an argparse usage message and a window that closes.
The CLI already treats "no command" as "open the panel"; this wrapper exists to
keep the window open long enough to read an error when one happens.
"""

import sys


def main() -> int:
    from devlink_mcp.cli import main as cli_main

    try:
        return cli_main()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:                       # noqa: BLE001 - last resort
        print(f"\nDevLink-MCP stopped: {exc}\n", file=sys.stderr)
        # Double-clicked from a file manager, the console vanishes on exit and
        # the message with it. Hold it until the person has read it.
        if sys.stdin is not None and sys.stdin.isatty():
            try:
                input("Press Enter to close...")
            except (EOFError, KeyboardInterrupt):
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())

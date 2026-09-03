# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Entry point for the frozen builds.

A shim: everything it does lives in ``devlink_mcp.desktop`` so the packaged
build and ``python -m devlink_mcp.desktop`` cannot drift apart, and so the
behaviour can be tested without freezing anything.
"""

import sys

from devlink_mcp.desktop import main

if __name__ == "__main__":
    sys.exit(main())

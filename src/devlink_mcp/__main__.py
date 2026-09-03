# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Allow ``python -m devlink_mcp``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

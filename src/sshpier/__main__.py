# Copyright 2026 sshpier contributors
# SPDX-License-Identifier: Apache-2.0
"""Allow ``python -m sshpier``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

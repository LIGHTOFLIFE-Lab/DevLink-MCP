#!/usr/bin/env bash
# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
#
# Build the Linux binary and tar it up.
#
#   bash packaging/build_linux.sh
#
# Output: dist/DevLink-MCP-<version>-linux-<arch>.tar.gz and a .sha256.
#
# A tarball rather than a bare file because a Linux desktop is the one place
# where the person doing the downloading expects to `tar xzf` and read a
# README, and where an executable bit is easy to lose.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(python3 -c 'import re,pathlib;print(re.search(r"^version = \"(.+?)\"", pathlib.Path("pyproject.toml").read_text(), re.M).group(1))')"
ARCH="$(uname -m)"
VENV="${VENV:-$ROOT/build/venv}"
NAME="DevLink-MCP-${VERSION}-linux-${ARCH}"

echo "==> environment"
python3 -m venv "$VENV"
# Always `python -m pip`, never the pip script: on Windows pip cannot replace
# its own running executable, and using the module form everywhere keeps the
# three build scripts saying the same thing. The upgrade is a convenience, so
# it is allowed to fail without stopping the build.
"$VENV/bin/python" -m pip install --quiet --upgrade pip || \
  echo "    (could not upgrade pip; continuing)"
"$VENV/bin/python" -m pip install --quiet pyinstaller pillow "paramiko>=2.11"
"$VENV/bin/python" -m pip install --quiet -e .

echo "==> binary"
"$VENV/bin/pyinstaller" packaging/devlink.spec --noconfirm --distpath dist --workpath build/pyi

echo "==> archive"
STAGE="build/tar/DevLink-MCP"
rm -rf "build/tar" && mkdir -p "$STAGE" dist
cp dist/DevLink-MCP LICENSE NOTICE README.md "$STAGE/"
chmod +x "$STAGE/DevLink-MCP"
tar czf "dist/${NAME}.tar.gz" -C build/tar DevLink-MCP
sha256sum "dist/${NAME}.tar.gz" > "dist/${NAME}.tar.gz.sha256"

echo "==> done"
ls -lh "dist/${NAME}.tar.gz"
cat "dist/${NAME}.tar.gz.sha256"

#!/usr/bin/env bash
# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
#
# Build DevLink-MCP.app and wrap it in a .dmg.
#
#   bash packaging/build_macos.sh
#
# Output: dist/DevLink-MCP-<version>-macos-<arch>.dmg and a .sha256 beside it.
#
# The result is ad-hoc signed, not notarised. Gatekeeper therefore asks the
# person who downloads it to confirm the first time (right-click > Open). A
# Developer ID certificate is the only way around that, and this project does
# not have one.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(python3 -c 'import re,pathlib;print(re.search(r"^version = \"(.+?)\"", pathlib.Path("pyproject.toml").read_text(), re.M).group(1))')"
ARCH="$(uname -m)"
VENV="${VENV:-$ROOT/build/venv}"
NAME="DevLink-MCP-${VERSION}-macos-${ARCH}"
DMG="dist/${NAME}.dmg"

echo "==> environment"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet pyinstaller pillow "paramiko>=2.11"
"$VENV/bin/pip" install --quiet -e .

echo "==> icon"
"$VENV/bin/python" packaging/make_icon.py build/icon.png
ICONSET="build/DevLink-MCP.iconset"
rm -rf "$ICONSET" && mkdir -p "$ICONSET"
for s in 16 32 64 128 256 512; do
  sips -z $s $s build/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) build/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
cp build/icon.png "$ICONSET/icon_512x512@2x.png"
iconutil -c icns "$ICONSET" -o packaging/DevLink-MCP.icns

echo "==> app bundle"
rm -rf dist/DevLink-MCP.app dist/DevLink-MCP
"$VENV/bin/pyinstaller" packaging/devlink.spec --noconfirm --distpath dist --workpath build/pyi

# Ad-hoc, so the bundle is at least internally consistent after we touched it.
echo "==> signature"
codesign --force --deep --sign - dist/DevLink-MCP.app

echo "==> disk image"
STAGE="build/dmg"
rm -rf "$STAGE" "$DMG" && mkdir -p "$STAGE" dist
cp -R dist/DevLink-MCP.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp LICENSE NOTICE "$STAGE/"
cp packaging/FIRST-RUN.txt "$STAGE/처음 실행하기 (READ ME FIRST).txt"
hdiutil create -volname "DevLink-MCP" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

shasum -a 256 "$DMG" > "$DMG.sha256"

echo "==> done"
ls -lh "$DMG"
cat "$DMG.sha256"

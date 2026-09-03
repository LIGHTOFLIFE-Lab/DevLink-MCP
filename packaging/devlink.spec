# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
#
# PyInstaller build. One spec for all three platforms — PyInstaller can only
# build for the system it runs on, so the release workflow runs this on a
# Windows, a macOS and a Linux runner.
#
#     pyinstaller packaging/devlink.spec --noconfirm
#
# Running the produced binary with no arguments opens the settings panel, which
# is what someone who double-clicks it wants. Subcommands still work:
#
#     DevLink-MCP serve --home ...

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent          # noqa: F821 - SPECPATH is injected
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# paramiko pulls in cryptography backends that are loaded by name, so the
# analysis cannot see them.
hidden = collect_submodules("paramiko") + collect_submodules("cryptography")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    # The example config is read by `devlink init`; without it the first run of
    # a downloaded build would produce an empty directory.
    datas=[(str(ROOT / "examples" / "servers.example.ini"), "devlink_mcp/data")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Nothing here needs a GUI toolkit; the panel is a web page.
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DevLink-MCP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Keep a console: the panel prints the URL it is listening on, and errors
    # would otherwise vanish. On macOS the .app wrapper below hides it.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if IS_MAC:
    app = BUNDLE(
        exe,
        name="DevLink-MCP.app",
        icon=None,
        bundle_identifier="io.github.lightoflife-lab.devlink-mcp",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleName": "DevLink-MCP",
            "NSHighResolutionCapable": True,
            # It opens a browser window rather than presenting a Cocoa UI.
            "LSBackgroundOnly": False,
        },
    )

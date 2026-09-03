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
# is what someone who double-clicks it wants. Subcommands still work, and have
# to: the MCP client is registered with a command line of
# `<this binary> serve --home ...` (see gui.launcher_command).
#
# Windows and Linux keep a console. The panel prints the address it is serving
# on, and closing that window is how you stop it — a background process with no
# window and no tray icon is worse than a plain terminal. On macOS the .app has
# a Dock icon, which does the same job.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent          # noqa: F821 - SPECPATH is injected
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# paramiko pulls in cryptography backends that are loaded by name, so the
# analysis cannot see them. They have to be in the box: someone who downloaded
# an executable cannot pip install the sync extra afterwards.
hidden = collect_submodules("paramiko") + collect_submodules("cryptography")

# Drawn by make_icon.py during the build; absent in a bare `pyinstaller` run,
# which is why every use below is guarded.
icon_mac = ROOT / "packaging" / "DevLink-MCP.icns"
icon_win = ROOT / "packaging" / "DevLink-MCP.ico"

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    # The example config is read by `devlink init`; without it the first run of
    # a downloaded build would produce an empty directory.
    datas=[(str(ROOT / "examples" / "servers.example.ini"), "devlink_mcp/data")],
    hiddenimports=hidden + ["devlink_mcp.mcpserver", "devlink_mcp.sync"],
    hookspath=[],
    runtime_hooks=[],
    # Nothing here needs a GUI toolkit; the panel is a web page. Pillow draws
    # the icon before the build and is not wanted inside it.
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

if IS_MAC:
    # A .app has to be a directory build: COLLECT, then BUNDLE. Folding the
    # binaries into a single file and wrapping that produces a bundle that
    # unpacks itself to a temporary directory on every launch.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="DevLink-MCP",
        debug=False,
        strip=False,
        upx=False,
        console=False,
        icon=str(icon_mac) if icon_mac.exists() else None,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DevLink-MCP")
    app = BUNDLE(
        coll,
        name="DevLink-MCP.app",
        icon=str(icon_mac) if icon_mac.exists() else None,
        bundle_identifier="io.github.lightoflife-lab.devlink-mcp",
        info_plist={
            "CFBundleName": "DevLink-MCP",
            "CFBundleDisplayName": "DevLink-MCP",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
else:
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
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(icon_win) if (IS_WINDOWS and icon_win.exists()) else None,
    )

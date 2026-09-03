# packaging

Everything needed to turn the package into something a person can download and
open. None of it is imported at runtime and none of it is in the wheel —
`pip install devlink-mcp` is unaffected by all of it.

| File | What it is |
|---|---|
| `entry.py` | The script PyInstaller freezes. A shim; the behaviour lives in [`devlink_mcp/desktop.py`](../src/devlink_mcp/desktop.py) so it can be tested without freezing anything. |
| `devlink.spec` | One PyInstaller spec, three platforms — a `.app` on macOS, a single file elsewhere. |
| `make_icon.py` | Draws the icon. Code rather than a checked-in binary, so a change to it is a readable diff. |
| `build_macos.sh` | venv → icon → `.app` → ad-hoc signature → `.dmg` → checksum. |
| `build_windows.ps1` | venv → icon → `.exe` → checksum. |
| `build_linux.sh` | venv → binary → `.tar.gz` → checksum. |
| `FIRST-RUN.txt` | Ships inside the disk image, next to the app. |

## Building

Each platform builds its own. PyInstaller does not cross-compile, and a `.dmg`
needs `hdiutil`, which exists only on macOS.

```bash
bash packaging/build_macos.sh                                          # on a Mac
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1   # on Windows
bash packaging/build_linux.sh                                          # on Linux
```

In practice you do not run these by hand. Pushing a tag makes
[`.github/workflows/release.yml`](../.github/workflows/release.yml) run all
four — Windows, Apple Silicon, Intel, Linux — smoke-test each one and attach
them to a GitHub Release:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

The smoke test is not a formality. It runs `--version`, `init` and `check`, and
then starts the panel and fetches a page from it. Two of those cover things
that only break in a frozen build: a missing `servers.example.ini`, and a
launcher that swallows its arguments.

## Why the frozen binary still takes subcommands

Someone who installed from a `.dmg` has no `devlink` on their PATH, and the
settings panel registers the MCP client with a command line of
`<this binary> serve --home …` — see `gui.launcher_command`, which has a branch
for `sys.frozen`. A launcher that opened the panel and ignored `argv` would
give them a panel they could not connect an assistant to.

## Two things the builds are not

**Signed.** Ad-hoc at best, so Gatekeeper and SmartScreen warn on first launch
and the person has to click through. Fixing that needs an Apple Developer ID
(annual fee, plus notarisation in the workflow) and an Authenticode
certificate. Until then the release notes, `FIRST-RUN.txt` and both READMEs say
which button to press.

**Universal.** The macOS build matches the machine that made it, which is why
the workflow runs on `macos-14` and `macos-13` and ships two disk images. A
universal2 binary would need a universal Python; two files is less clever and
always works.

## Why a browser instead of a desktop toolkit

The same reason `devlink gui` uses one — see the note at the top of
[`gui.py`](../src/devlink_mcp/gui.py). Freezing a web panel also keeps the
download small: no Qt, no tkinter, about 15 MB.

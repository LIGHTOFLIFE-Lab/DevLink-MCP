# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
#
# Build DevLink-MCP.exe - a single file, no Python installation required.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#
# Output: dist\DevLink-MCP-<version>-windows-x64.exe and a .sha256 beside it.
#
# Deliberately not a zip. Unpacking is a step, and the whole point of this
# build is that someone can download one file and open it. The licence travels
# with the repository and the release page.
#
# The result is unsigned, so SmartScreen shows "Windows protected your PC" the
# first time and the person has to choose More info > Run anyway. An
# Authenticode certificate is the only way around that.
#
# Two things about this file, both learned the hard way:
#
#   1. It is saved with a UTF-8 BOM and kept to ASCII. Windows PowerShell 5.1
#      reads a BOM-less .ps1 as ANSI, which mangles anything non-ASCII. The
#      BOM is the belt; staying ASCII is the braces.
#   2. $ErrorActionPreference does not apply to native programs. python, pip
#      and pyinstaller can fail and the script would sail on to a misleading
#      error further down, so every one of them is checked explicitly.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Step {
    param([string]$What, [scriptblock]$Body)
    # Native programs are judged by their exit code, not by whether they wrote
    # to stderr. pip and pyinstaller both report ordinary progress there, and
    # with ErrorActionPreference = Stop in Windows PowerShell that can raise
    # NativeCommandError before we ever get to look at the exit code. So the
    # preference is relaxed for the duration of the call and restored after.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $global:LASTEXITCODE = 0
        & $Body
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        throw "$What failed (exit $code)"
    }
}

# --- find a usable Python ------------------------------------------------
# `py` first: it is the launcher that a python.org install provides. Plain
# `python` on a machine without Python is an App Execution Alias that opens the
# Microsoft Store and returns success, which would otherwise look like a
# working interpreter that silently does nothing.
$py = $null
foreach ($candidate in @(@("py", "-3"), @("python"))) {
    $exe = $candidate[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $args = @($candidate[1..($candidate.Length - 1)]) + @("-c", "import sys; print(sys.version_info[:2])")
    $probe = & $exe @args 2>$null
    if ($LASTEXITCODE -eq 0 -and $probe) {
        $py = $candidate
        Write-Host "==> python: $exe $probe"
        break
    }
}
if (-not $py) {
    throw "No working Python found. Install Python 3.9+ from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
}
$pyExe = $py[0]
$pyArgs = @($py[1..($py.Length - 1)])

$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+?)"').Matches[0].Groups[1].Value
$venv = if ($env:VENV) { $env:VENV } else { "$root\build\venv" }
$out = "dist\DevLink-MCP-$version-windows-x64.exe"

Write-Host "==> environment"
Invoke-Step "creating the build virtualenv" { & $pyExe @pyArgs -m venv $venv }

$venvPy = "$venv\Scripts\python.exe"
$venvPyi = "$venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $venvPy)) { throw "the virtualenv has no python: $venvPy" }

# Always `python -m pip`, never `pip.exe`. On Windows pip cannot replace its own
# running executable, so `pip.exe install --upgrade pip` fails outright and pip
# itself tells you to use the module form.
#
# The upgrade is a convenience, not a requirement: an old pip still installs
# these packages. A failure here must not stop a build, so it is the one step
# that is allowed to fail.
Write-Host "==> pip"
$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $venvPy -m pip install --quiet --upgrade pip
$pipUpgrade = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($pipUpgrade -ne 0) {
    Write-Host "    (could not upgrade pip; continuing with the version in the venv)"
}

Invoke-Step "installing build deps" { & $venvPy -m pip install --quiet pyinstaller pillow "paramiko>=2.11" }
Invoke-Step "installing DevLink-MCP" { & $venvPy -m pip install --quiet -e . }

Write-Host "==> icon"
Invoke-Step "drawing the icon" { & $venvPy packaging\make_icon.py build\icon.png }
Invoke-Step "converting the icon" {
    & $venvPy -c "from PIL import Image; Image.open(r'build\icon.png').save(r'packaging\DevLink-MCP.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
}

Write-Host "==> executable"
Invoke-Step "pyinstaller" {
    & $venvPyi packaging\devlink.spec --noconfirm --distpath dist --workpath build\pyi
}

# PyInstaller reports success even when the spec produced something other than
# what we expect, so confirm the file is really there before renaming it.
if (-not (Test-Path "dist\DevLink-MCP.exe")) {
    throw "pyinstaller finished but dist\DevLink-MCP.exe is missing. Check build\pyi for the reason."
}
Move-Item -Force "dist\DevLink-MCP.exe" $out

Write-Host "==> smoke test"
Invoke-Step "running the built executable" { & ".\$out" --version }

(Get-FileHash $out -Algorithm SHA256).Hash.ToLower() + "  " + (Split-Path $out -Leaf) |
  Out-File -Encoding ascii "$out.sha256"

Write-Host "==> done"
Get-Item $out | Format-List Name, Length
Get-Content "$out.sha256"

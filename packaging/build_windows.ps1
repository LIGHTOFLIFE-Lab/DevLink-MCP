# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
#
# Build DevLink-MCP.exe — a single file, no Python installation required.
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

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+?)"').Matches[0].Groups[1].Value
$venv = if ($env:VENV) { $env:VENV } else { "$root\build\venv" }
$out = "dist\DevLink-MCP-$version-windows-x64.exe"

Write-Host "==> environment"
python -m venv $venv
& "$venv\Scripts\pip.exe" install --quiet --upgrade pip
& "$venv\Scripts\pip.exe" install --quiet pyinstaller pillow "paramiko>=2.11"
& "$venv\Scripts\pip.exe" install --quiet -e .

Write-Host "==> icon"
& "$venv\Scripts\python.exe" packaging\make_icon.py build\icon.png
& "$venv\Scripts\python.exe" -c "from PIL import Image; Image.open(r'build\icon.png').save(r'packaging\DevLink-MCP.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

Write-Host "==> executable"
& "$venv\Scripts\pyinstaller.exe" packaging\devlink.spec --noconfirm --distpath dist --workpath build\pyi
Move-Item -Force dist\DevLink-MCP.exe $out

(Get-FileHash $out -Algorithm SHA256).Hash.ToLower() + "  " + (Split-Path $out -Leaf) |
  Out-File -Encoding ascii "$out.sha256"

Write-Host "==> done"
Get-Item $out | Format-List Name, Length
Get-Content "$out.sha256"

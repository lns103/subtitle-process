#Requires -Version 5.1
<#
.SYNOPSIS
    Rename Windows bundle outputs to ASCII-only names for GitHub Releases.

.DESCRIPTION
    GitHub release assets strip non-ASCII characters from filenames (for example
    `字幕工具箱_1.0.0-alpha2_x64-setup.exe` becomes `_1.0.0-alpha2_x64-setup.exe`).
    Tauri names the NSIS installer after `productName`, so this script renames the
    generated installer to `subtitle-process_<version>_<arch>-setup.exe`.

    Portable ZIPs are already produced with an ASCII name by
    `scripts/package-portable.ps1`.
#>
[CmdletBinding()]
param(
    [string]$Version
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
# 应用版本号唯一来源是 apps/desktop/package.json（tauri.conf.json 的 version 指向它）。
$PackageJsonPath = Join-Path $RepoRoot "apps\desktop\package.json"
$NsisDir = Join-Path $RepoRoot "apps\desktop\src-tauri\target\release\bundle\nsis"

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = [string](Get-Content -LiteralPath $PackageJsonPath -Raw | ConvertFrom-Json).version
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    throw "Unable to determine app version."
}

if (-not (Test-Path -LiteralPath $NsisDir)) {
    throw "NSIS output directory not found: $NsisDir"
}

$installers = @(Get-ChildItem -LiteralPath $NsisDir -Filter "*.exe" -File)
if ($installers.Count -eq 0) {
    throw "No NSIS installer found in $NsisDir"
}

$target = Join-Path $NsisDir "subtitle-process_${Version}_x64-setup.exe"
foreach ($installer in $installers) {
    if ($installer.FullName -eq $target) {
        continue
    }
    Move-Item -LiteralPath $installer.FullName -Destination $target -Force
}

Write-Host "NSIS installer: $target"

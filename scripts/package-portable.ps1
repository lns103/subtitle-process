#Requires -Version 5.1
<#
.SYNOPSIS
    Package the built Tauri app into a portable (no-install) ZIP.

.DESCRIPTION
    Collects the release executable and the Python sidecar from
    `apps/desktop/src-tauri/target/release/` into:

        apps/desktop/src-tauri/target/release/bundle/portable/<product>_<version>_<arch>-portable.zip

    The ZIP is flat: `subtitle-desktop.exe` and `subtitle-engine.exe` must stay in
    the same directory at runtime.

.PARAMETER TargetTriple
    Target triple used in the archive name. Defaults to `rustc -vV` host or
    `x86_64-pc-windows-msvc`.

.PARAMETER Version
    Overrides the version from `tauri.conf.json`.

.EXAMPLE
    pwsh scripts/package-portable.ps1
#>
[CmdletBinding()]
param(
    [string]$TargetTriple,
    [string]$Version
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$TauriConfPath = Join-Path $RepoRoot "apps\desktop\src-tauri\tauri.conf.json"
$ReleaseDir = Join-Path $RepoRoot "apps\desktop\src-tauri\target\release"

if (-not (Test-Path -LiteralPath $TauriConfPath)) {
    throw "tauri.conf.json not found: $TauriConfPath"
}

$config = Get-Content -LiteralPath $TauriConfPath -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = [string]$config.version
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    throw "Unable to determine app version."
}

if ([string]::IsNullOrWhiteSpace($TargetTriple)) {
    $rustc = Get-Command rustc -ErrorAction SilentlyContinue
    if ($null -ne $rustc) {
        $hostLine = & rustc -vV 2>$null | Select-String -Pattern '^host:\s*(.+)$' | Select-Object -First 1
        if ($null -ne $hostLine) {
            $TargetTriple = $hostLine.Matches[0].Groups[1].Value.Trim()
        }
    }
    if ([string]::IsNullOrWhiteSpace($TargetTriple)) {
        $TargetTriple = "x86_64-pc-windows-msvc"
    }
}

$extension = if ($TargetTriple -like "*windows*") { ".exe" } else { "" }
$mainExe = Join-Path $ReleaseDir ("subtitle-desktop" + $extension)
$sidecarExe = Join-Path $ReleaseDir ("subtitle-engine" + $extension)

foreach ($path in @($mainExe, $sidecarExe)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing build output: $path. Run 'npm run tauri build' first."
    }
}

$arch = if ($TargetTriple -like "*aarch64*") {
    "arm64"
}
elseif ($TargetTriple -like "*i686*") {
    "x86"
}
else {
    "x64"
}

$productName = if ([string]::IsNullOrWhiteSpace([string]$config.productName)) {
    "SubtitleProcess"
}
else {
    [string]$config.productName
}
$baseName = "${productName}_${Version}_${arch}-portable"
$outDir = Join-Path $ReleaseDir "bundle\portable"
$zipPath = Join-Path $outDir ($baseName + ".zip")
$stageDir = Join-Path ([System.IO.Path]::GetTempPath()) ("subtitle-portable-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))

try {
    New-Item -ItemType Directory -Force -Path $outDir, $stageDir | Out-Null

    Copy-Item -LiteralPath $mainExe -Destination (Join-Path $stageDir (Split-Path -Leaf $mainExe)) -Force
    Copy-Item -LiteralPath $sidecarExe -Destination (Join-Path $stageDir (Split-Path -Leaf $sidecarExe)) -Force

    $readme = @(
        "$productName $Version (portable / 免安装)"
        ""
        "1. 解压后双击 subtitle-desktop.exe 启动。"
        "2. subtitle-engine.exe 必须和主程序放在同一目录，不要单独移动。"
        "3. 需要系统已安装 WebView2（Windows 10/11 通常已自带）。"
        "4. 数据默认保存在 %APPDATA%\SubtitleProcess。"
    ) -join "`n"
    [System.IO.File]::WriteAllText(
        (Join-Path $stageDir "README.txt"),
        $readme + "`n",
        (New-Object System.Text.UTF8Encoding($false))
    )

    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $stageDir "*") -DestinationPath $zipPath -CompressionLevel Optimal

    Write-Host "Portable package: $zipPath"
    Write-Host ("Size: {0:N1} MB" -f ((Get-Item -LiteralPath $zipPath).Length / 1MB))
}
finally {
    if (Test-Path -LiteralPath $stageDir) {
        Remove-Item -LiteralPath $stageDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

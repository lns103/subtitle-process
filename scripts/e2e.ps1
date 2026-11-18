#Requires -Version 5.1
<#
.SYNOPSIS
    End-to-end smoke test for the subtitle-engine CLI (no GUI, no Tauri).

.DESCRIPTION
    Flow:
      1. Generate a 4s MKV with an embedded English SRT track (ffmpeg).
      2. Create a project through the engine RPC layer (project.create).
      3. Run batch_video_to_clean_srt.yaml and assert a *.srt artifact exists.
      4. Generate a Chinese SRT with the same timeline, then run
         batch_translated_to_bilingual.yaml against the same project.

    The bilingual steps (sub.match_project / sub.merge_bilingual) are registered by
    the engine. Set SUBTITLE_E2E_SKIP_BILINGUAL=1 to run only the first phase.

.PARAMETER KeepArtifacts
    Keep the temporary working directory (video, data dir, logs) for inspection.

.EXAMPLE
    pwsh scripts/e2e.ps1

.EXAMPLE
    $env:SUBTITLE_E2E_SKIP_BILINGUAL = "1"; pwsh scripts/e2e.ps1

.NOTES
    Environment variables:
      SUBTITLE_E2E_SKIP_BILINGUAL=1     always skip the bilingual phase
      SUBTITLE_E2E_STRICT_BILINGUAL=1   fail when bilingual steps are missing
      SUBTITLE_E2E_FFMPEG=<path>        ffmpeg executable override
      SUBTITLE_E2E_FFPROBE=<path>       ffprobe executable override
#>
[CmdletBinding()]
param(
    [switch]$KeepArtifacts
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EngineDir = Join-Path $RepoRoot "engine"
$RecipesDir = Join-Path $EngineDir "src\subtitle_engine\recipes"
$VideoRecipe = Join-Path $RecipesDir "batch_video_to_clean_srt.yaml"
$BilingualRecipe = Join-Path $RecipesDir "batch_translated_to_bilingual.yaml"

$WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ("subtitle-e2e-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
$DataDir = Join-Path $WorkDir "data"
$VideoPath = Join-Path $WorkDir "EP01.mkv"
$SourceSrt = Join-Path $WorkDir "sample.srt"
$ChineseSrt = Join-Path $WorkDir "EP01.zh.srt"
$ProjectHelper = Join-Path $WorkDir "make_project.py"

$Ffmpeg = if ($env:SUBTITLE_E2E_FFMPEG) { $env:SUBTITLE_E2E_FFMPEG } else { "ffmpeg" }
$Ffprobe = if ($env:SUBTITLE_E2E_FFPROBE) { $env:SUBTITLE_E2E_FFPROBE } else { "ffprobe" }

# Keep engine stdout/stderr UTF-8 so Chinese subtitles survive the CLI round trip.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Skip {
    param([string]$Message)
    Write-Host "!!  SKIP: $Message" -ForegroundColor Yellow
}

function Write-Utf8LfFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string[]]$Lines
    )
    $text = ($Lines -join "`n") + "`n"
    [System.IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

function Invoke-EngineRun {
    <#
        Runs `uv run python -m subtitle_engine <Arguments>` from engine/.
        Engine output goes to the host (not the pipeline), the exit code is returned.
    #>
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    Push-Location $EngineDir
    try {
        & uv run python -m subtitle_engine @Arguments | Out-Host
        return $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

function Get-RegisteredStepIds {
    Push-Location $EngineDir
    try {
        $code = 'from subtitle_engine import steps; from subtitle_engine.core.registry import all_steps; print(",".join(sorted(s.id for s in all_steps())))'
        $raw = & uv run python -c $code 2>$null
        return (@($raw) -join "`n")
    }
    finally {
        Pop-Location
    }
}

$exitCode = 0
try {
    Write-Step "Checking prerequisites"
    if ($null -eq (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is not on PATH. Install it first: https://docs.astral.sh/uv/"
    }
    if ($null -eq (Get-Command $Ffmpeg -ErrorAction SilentlyContinue)) {
        throw "ffmpeg not found (set SUBTITLE_E2E_FFMPEG to override)."
    }
    if ($null -eq (Get-Command $Ffprobe -ErrorAction SilentlyContinue)) {
        throw "ffprobe not found (set SUBTITLE_E2E_FFPROBE to override)."
    }
    foreach ($recipe in @($VideoRecipe, $BilingualRecipe)) {
        if (-not (Test-Path -LiteralPath $recipe)) {
            throw "Recipe not found: $recipe"
        }
    }

    New-Item -ItemType Directory -Force -Path $WorkDir, $DataDir | Out-Null
    Write-Host "    work dir: $WorkDir"

    Write-Step "Creating test subtitle and MKV"
    Write-Utf8LfFile -Path $SourceSrt -Lines @(
        "1",
        "00:00:00,200 --> 00:00:01,000",
        "[BEN]: (laughs) Hello <b>there</b>",
        "",
        "2",
        "00:00:01,050 --> 00:00:01,800",
        "I think this",
        "",
        "3",
        "00:00:01,900 --> 00:00:03,500",
        "sentence is split"
    )

    $ffmpegArgs = @(
        "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x120:d=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-i", $SourceSrt,
        "-map", "0:v", "-map", "1:a", "-map", "2:s",
        "-c:v", "mpeg4", "-c:a", "aac", "-c:s", "srt",
        "-metadata:s:a:0", "language=eng",
        "-metadata:s:s:0", "language=eng",
        "-shortest",
        $VideoPath
    )
    Push-Location $WorkDir
    try {
        & $Ffmpeg @ffmpegArgs
        $ffmpegCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($ffmpegCode -ne 0) {
        throw "ffmpeg failed to create the test MKV (exit $ffmpegCode)."
    }
    if (-not (Test-Path -LiteralPath $VideoPath)) {
        throw "ffmpeg reported success but the MKV is missing: $VideoPath"
    }

    Write-Step "Creating engine project (project.create via RPC)"
    $helperSource = @'
import asyncio
import sys
from pathlib import Path

from subtitle_engine.rpc.server import RpcServer


async def main() -> int:
    data_dir = Path(sys.argv[1])
    media_path = sys.argv[2]
    server = RpcServer(sink=lambda _message: None, data_dir=data_dir)
    try:
        project = await server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "project.create",
                "params": {"media_path": media_path, "name": "E2E"},
            }
        )
    finally:
        server.close()
    print(project["id"])
    return 0


raise SystemExit(asyncio.run(main()))
'@
    [System.IO.File]::WriteAllText(
        $ProjectHelper,
        $helperSource,
        (New-Object System.Text.UTF8Encoding($false))
    )

    Push-Location $EngineDir
    try {
        $projectId = (& uv run python $ProjectHelper $DataDir $VideoPath | Select-Object -Last 1)
    }
    finally {
        Pop-Location
    }
    if ($null -eq $projectId -or ([string]$projectId).Trim().Length -eq 0) {
        throw "project.create did not return a project id."
    }
    $projectId = ([string]$projectId).Trim()
    Write-Host "    project id: $projectId"

    Write-Step "Phase 1: batch_video_to_clean_srt (CLI)"
    $videoCode = Invoke-EngineRun @(
        "run", $VideoRecipe,
        "--input", $VideoPath,
        "--data-dir", $DataDir,
        "--project-id", $projectId
    )
    if ($videoCode -ne 0) {
        throw "batch_video_to_clean_srt failed with exit code $videoCode (see CLI output above)."
    }

    $cleanOutputs = @(
        Get-ChildItem -LiteralPath (Join-Path $DataDir "projects\$projectId\output") -File -Filter "*.srt" -ErrorAction SilentlyContinue
    )
    if ($cleanOutputs.Count -eq 0) {
        throw "Phase 1 finished but no *.srt was produced under $DataDir\projects\$projectId\output"
    }
    foreach ($file in $cleanOutputs) {
        Write-Host "    clean SRT: $($file.FullName)"
    }
    Write-Host "PASS: batch_video_to_clean_srt" -ForegroundColor Green

    if ($env:SUBTITLE_E2E_SKIP_BILINGUAL -eq "1") {
        Write-Skip "batch_translated_to_bilingual (SUBTITLE_E2E_SKIP_BILINGUAL=1)"
        Write-Host ""
        Write-Host "E2E finished: phase 1 passed, bilingual skipped." -ForegroundColor Green
    }
    else {
        Write-Step "Checking bilingual step availability"
        $stepIds = Get-RegisteredStepIds
        $bilingualReady = ($stepIds -match "sub\.match_project") -and ($stepIds -match "sub\.merge_bilingual")
        if (-not $bilingualReady) {
            $message = "sub.match_project / sub.merge_bilingual are not registered."
            if ($env:SUBTITLE_E2E_STRICT_BILINGUAL -eq "1") {
                throw "$message SUBTITLE_E2E_STRICT_BILINGUAL=1 is set."
            }
            Write-Skip "batch_translated_to_bilingual: $message"
            Write-Host "    known steps: $stepIds"
            Write-Host "    check steps/__init__.py registration and re-run."
            Write-Host ""
            Write-Host "E2E finished: phase 1 passed, bilingual skipped." -ForegroundColor Green
        }
        else {
            Write-Step "Phase 2: batch_translated_to_bilingual (CLI)"
            Write-Utf8LfFile -Path $ChineseSrt -Lines @(
                "1",
                "00:00:00,200 --> 00:00:01,000",
                "（笑）你好啊",
                "",
                "2",
                "00:00:01,050 --> 00:00:01,800",
                "我觉得这",
                "",
                "3",
                "00:00:01,900 --> 00:00:03,500",
                "句话被拆开了"
            )

            $bilingualCode = Invoke-EngineRun @(
                "run", $BilingualRecipe,
                "--input-name", "original=$($cleanOutputs[0].FullName)",
                "--input-name", "translated=$ChineseSrt",
                "--data-dir", $DataDir,
                "--project-id", $projectId
            )
            if ($bilingualCode -ne 0) {
                throw "batch_translated_to_bilingual failed with exit code $bilingualCode (see CLI output above)."
            }

            $assOutputs = @(
                Get-ChildItem -LiteralPath $DataDir -Recurse -File -Filter "*.ass" -ErrorAction SilentlyContinue
            )
            if ($assOutputs.Count -eq 0) {
                throw "Phase 2 finished but no bilingual *.ass was produced under $DataDir"
            }
            foreach ($file in $assOutputs) {
                Write-Host "    bilingual ASS: $($file.FullName)"
            }
            Write-Host "PASS: batch_translated_to_bilingual" -ForegroundColor Green
            Write-Host ""
            Write-Host "E2E finished: both phases passed." -ForegroundColor Green
        }
    }
}
catch {
    Write-Host ""
    Write-Host "E2E failed: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
}
finally {
    if ($KeepArtifacts) {
        Write-Host "Artifacts kept: $WorkDir"
    }
    elseif (Test-Path $WorkDir) {
        Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit $exitCode

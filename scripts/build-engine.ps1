#Requires -Version 5.1
<#
.SYNOPSIS
    Build the Python engine (engine/) into a Tauri v2 sidecar binary.

.DESCRIPTION
    Primary toolchain: Nuitka onefile.
    Fallback toolchain: PyInstaller onefile (also used when -Fallback is set).

    Both toolchains produce a single self-contained executable so that Tauri's
    `bundle.externalBin` (which ships only the sidecar file) is enough at runtime.

    The produced executable is copied to:
        apps/desktop/src-tauri/binaries/subtitle-engine-<target-triple>[.exe]
    which is exactly what `bundle.externalBin` in tauri.conf.json expects.

.PARAMETER Fallback
    Skip Nuitka and build with PyInstaller onefile directly.

.PARAMETER TargetTriple
    Override the Rust target triple. Defaults to the `host:` line of `rustc -vV`,
    or `x86_64-pc-windows-msvc` when rustc is unavailable.

.EXAMPLE
    pwsh scripts/build-engine.ps1

.EXAMPLE
    pwsh scripts/build-engine.ps1 -Fallback -TargetTriple x86_64-pc-windows-msvc

.NOTES
    - Toolchains are executed through `uv` from the engine/ directory, so the
      engine virtualenv (and its dependencies) is always used.
    - Nuitka is auto-detected in the engine environment. When missing, the
      script falls back to `uv run --with nuitka` and prints the `uv add --dev
      nuitka` tip. Same for PyInstaller.
    - Set SUBTITLE_KEEP_BUILD_DIR=1 to keep the temporary build directory.
#>
[CmdletBinding()]
param(
    [switch]$Fallback,
    [string]$TargetTriple
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EngineDir = Join-Path $RepoRoot "engine"
$BinDir = Join-Path $RepoRoot "apps\desktop\src-tauri\binaries"
$EntryPoint = Join-Path $EngineDir "src\subtitle_engine\__main__.py"
$BuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("subtitle-engine-build-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
$NuitkaOut = Join-Path $BuildRoot "nuitka"
$PyiDist = Join-Path $BuildRoot "pyinstaller-dist"
$PyiWork = Join-Path $BuildRoot "pyinstaller-work"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($exitCode -ne 0) {
        throw "Command failed with exit code ${exitCode}: $FilePath $($Arguments -join ' ')"
    }
}

function Test-UvModule {
    <#
        Returns $true when <Module> is already available inside the engine environment
        (i.e. `uv run python -m <Module> --version` succeeds).
    #>
    param([Parameter(Mandatory = $true)][string]$Module)

    Push-Location $EngineDir
    try {
        & uv run python -m $Module --version *> $null
        return ($LASTEXITCODE -eq 0)
    }
    finally {
        Pop-Location
    }
}

function Resolve-TargetTriple {
    param([string]$Explicit)

    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        return $Explicit.Trim()
    }

    $rustc = Get-Command rustc -ErrorAction SilentlyContinue
    if ($null -ne $rustc) {
        $hostLine = & rustc -vV 2>$null | Select-String -Pattern '^host:\s*(.+)$' | Select-Object -First 1
        if ($null -ne $hostLine) {
            return $hostLine.Matches[0].Groups[1].Value.Trim()
        }
    }

    Write-Warning "rustc not found; assuming x86_64-pc-windows-msvc. Pass -TargetTriple to override."
    return "x86_64-pc-windows-msvc"
}

function Get-EngineVersion {
    param([Parameter(Mandatory = $true)][string]$BinaryPath)

    try {
        $output = (& $BinaryPath --version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0) {
            if ([string]::IsNullOrWhiteSpace($output)) {
                Write-Host "    smoke test: exit 0 (no stdout; GUI-subsystem PyInstaller build)"
            }
            else {
                Write-Host "    smoke test: $output"
            }
        }
        else {
            Write-Warning "Sidecar smoke test exited with $LASTEXITCODE (build output kept)."
        }
    }
    catch {
        Write-Warning "Sidecar smoke test could not run: $($_.Exception.Message)"
    }
}

$exitCode = 0
try {
    Write-Step "Checking prerequisites"
    if (-not (Test-Path (Join-Path $EngineDir "pyproject.toml"))) {
        throw "engine/pyproject.toml not found; run this script from the repository (expected: $EngineDir)."
    }
    if (-not (Test-Path $EntryPoint)) {
        throw "Engine entry point not found: $EntryPoint"
    }
    if ($null -eq (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is not on PATH. Install it first: https://docs.astral.sh/uv/"
    }

    $triple = Resolve-TargetTriple -Explicit $TargetTriple
    $extension = if ($triple -like "*windows*") { ".exe" } else { "" }
    $destPath = Join-Path $BinDir ("subtitle-engine-" + $triple + $extension)

    Write-Step "Target triple: $triple"
    New-Item -ItemType Directory -Force -Path $BuildRoot, $NuitkaOut, $PyiWork, $PyiDist, $BinDir | Out-Null

    # engine/src/subtitle_engine/__main__.py uses package-relative imports
    # (`from .version import ...`). Compiling that file directly produces a
    # binary that dies with "attempted relative import with no known parent
    # package" (Nuitka warns about this explicitly). Both toolchains therefore
    # start from a 2-line absolute-import launcher instead; the package itself
    # is pulled in via --include-package / --collect-submodules.
    $LauncherPath = Join-Path $BuildRoot "engine_entry.py"
    @(
        "from subtitle_engine.__main__ import main"
        ""
        "if __name__ == ""__main__"":"
        "    raise SystemExit(main())"
    ) | Set-Content -LiteralPath $LauncherPath -Encoding ASCII

    $built = $false
    $mode = ""

    if (-not $Fallback) {
        Write-Step "Building with Nuitka (onefile)"
        $nuitkaInEnv = Test-UvModule -Module "nuitka"
        $nuitkaArgs = @("run")
        if (-not $nuitkaInEnv) {
            Write-Warning "nuitka is not installed in the engine environment."
            Write-Warning "  tip: cd engine; uv add --dev nuitka    (or let this script use: uv run --with nuitka)"
            $nuitkaArgs += @("--with", "nuitka")
        }
        $nuitkaArgs += @(
            "python",
            "-m",
            "nuitka",
            "--onefile",
            "--assume-yes-for-downloads",
            "--include-package=subtitle_engine",
            "--include-package-data=subtitle_engine",
            "--output-filename=subtitle-engine",
            "--output-dir=$NuitkaOut",
            $LauncherPath
        )

        try {
            Invoke-Native -FilePath "uv" -Arguments $nuitkaArgs -WorkingDirectory $EngineDir
            $nuitkaBinary = Join-Path $NuitkaOut ("subtitle-engine" + $extension)
            if (-not (Test-Path $nuitkaBinary)) {
                throw "Nuitka finished but the expected binary is missing: $nuitkaBinary"
            }
            Copy-Item -LiteralPath $nuitkaBinary -Destination $destPath -Force
            $built = $true
            $mode = "nuitka onefile"
        }
        catch {
            Write-Warning "Nuitka build failed: $($_.Exception.Message)"
            Write-Warning "Falling back to PyInstaller onefile."
        }
    }
    else {
        Write-Step "-Fallback set: skipping Nuitka"
    }

    if (-not $built) {
        Write-Step "Building with PyInstaller (onefile)"
        $pyinstallerInEnv = Test-UvModule -Module "PyInstaller"
        $pyiArgs = @("run")
        if (-not $pyinstallerInEnv) {
            Write-Warning "pyinstaller is not installed in the engine environment."
            Write-Warning "  tip: cd engine; uv add --dev pyinstaller  (or let this script use: uv run --with pyinstaller)"
            $pyiArgs += @("--with", "pyinstaller")
        }

        # __main__.py uses relative imports, so a tiny absolute-import launcher is
        # required for PyInstaller (it does not treat the script as a package member).
        # --onefile keeps the sidecar self-contained: Tauri's `externalBin` copies a
        # single file, so an onedir build would lose its `_internal/` payload.
        $pyiArgs += @(
            "python",
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--noconsole",
            "--name", "subtitle-engine",
            "--distpath", $PyiDist,
            "--workpath", $PyiWork,
            "--specpath", $PyiWork,
            "--paths", (Join-Path $EngineDir "src"),
            "--collect-submodules", "subtitle_engine",
            "--collect-data", "subtitle_engine",
            $LauncherPath
        )

        Invoke-Native -FilePath "uv" -Arguments $pyiArgs -WorkingDirectory $EngineDir

        # onefile puts the executable directly in distpath (no app directory).
        $pyiBinary = Join-Path $PyiDist ("subtitle-engine" + $extension)
        if (-not (Test-Path $pyiBinary)) {
            throw "PyInstaller finished but the expected binary is missing: $pyiBinary"
        }
        Copy-Item -LiteralPath $pyiBinary -Destination $destPath -Force

        # Remove the stale `_internal/` left by older onedir builds; it is not
        # needed by onefile and only confuses the sidecar layout.
        $staleInternal = Join-Path $BinDir "_internal"
        if (Test-Path $staleInternal) {
            Remove-Item -LiteralPath $staleInternal -Recurse -Force
            Write-Host "    removed stale '_internal' directory from $BinDir"
        }

        $built = $true
        $mode = "pyinstaller onefile"
    }

    Write-Step "Verifying sidecar"
    Write-Host "    mode: $mode"
    Write-Host "    file: $destPath"
    Write-Host ("    size: {0:N1} MB" -f ((Get-Item -LiteralPath $destPath).Length / 1MB))
    Get-EngineVersion -BinaryPath $destPath

    Write-Host ""
    Write-Host "Sidecar ready. Next steps:" -ForegroundColor Green
    Write-Host "  cd apps/desktop"
    Write-Host "  npm run tauri build        # bundling picks up binaries/subtitle-engine-<triple>"
}
catch {
    Write-Host ""
    Write-Host "Engine build failed: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
}
finally {
    if ($env:SUBTITLE_KEEP_BUILD_DIR -eq "1") {
        Write-Host "Build directory kept: $BuildRoot"
    }
    elseif (Test-Path $BuildRoot) {
        Remove-Item -LiteralPath $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit $exitCode

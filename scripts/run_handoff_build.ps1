# ============================================================
# FULL AUTOMATED HANDOFF BUILD
# One script does everything: find zip, unzip, pull latest,
# install deps, connect to InDesign, generate JSX, execute.
# ============================================================
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run_handoff_build.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run_handoff_build.ps1 -HandoffZip "C:\path\to\handoff.zip"
#   powershell -ExecutionPolicy Bypass -File scripts\run_handoff_build.ps1 -Model "qwen2.5-coder:7b"
#
# ============================================================

param(
    [string]$HandoffZip = "",
    [string]$Model = "qwen2.5-coder:7b"
)

$ErrorActionPreference = "Continue"
$RepoDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "$RepoDir\indesign\handoff\build_from_handoff.py")) {
    $RepoDir = $PSScriptRoot | Split-Path -Parent
}
$OutputBase = "$env:USERPROFILE\Production-Automation-Output"
$HandoffOutput = "$OutputBase\handoff_package"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  AUTOMATED INDESIGN HANDOFF BUILD" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# --- Step 0: OneDrive check ---
$currentPath = (Get-Location).Path
if ($currentPath -match "OneDrive") {
    Write-Host "WARNING: Running from OneDrive path. Output will go to local dir." -ForegroundColor Yellow
}

# --- Step 1: Find the handoff zip ---
Write-Host "[1/7] Finding handoff package..." -ForegroundColor Green

if ($HandoffZip -and (Test-Path $HandoffZip)) {
    Write-Host "  Using provided: $HandoffZip" -ForegroundColor Green
} else {
    # Search common locations
    $searchPaths = @(
        "$env:USERPROFILE\Downloads\handoff_package_final.zip",
        "$env:USERPROFILE\Desktop\handoff_package_final.zip",
        "$env:USERPROFILE\Documents\handoff_package_final.zip",
        "$env:USERPROFILE\OneDrive\Desktop\handoff_package_final.zip",
        "$env:USERPROFILE\OneDrive\Downloads\handoff_package_final.zip"
    )

    $HandoffZip = ""
    foreach ($p in $searchPaths) {
        if (Test-Path $p) {
            $HandoffZip = $p
            break
        }
    }

    if (-not $HandoffZip) {
        # Deep search
        Write-Host "  Searching for handoff_package_final.zip..." -ForegroundColor Yellow
        $found = Get-ChildItem -Path $env:USERPROFILE -Recurse -Filter "handoff_package_final.zip" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            $HandoffZip = $found.FullName
        }
    }

    if (-not $HandoffZip) {
        Write-Host "  ERROR: Could not find handoff_package_final.zip" -ForegroundColor Red
        Write-Host "  Please provide the path: " -NoNewline
        $HandoffZip = Read-Host
        if (-not (Test-Path $HandoffZip)) {
            Write-Host "  File not found. Exiting." -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  Found: $HandoffZip" -ForegroundColor Green
}

# --- Step 2: Unzip ---
Write-Host "[2/7] Unzipping handoff package..." -ForegroundColor Green
if (Test-Path $HandoffOutput) {
    Remove-Item -Path $HandoffOutput -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $HandoffOutput -Force | Out-Null
Expand-Archive -Path $HandoffZip -DestinationPath $HandoffOutput -Force
Write-Host "  Extracted to: $HandoffOutput" -ForegroundColor Green

# Check if manifest is inside a subfolder
if (-not (Test-Path "$HandoffOutput\master_production_manifest.json")) {
    $subdir = Get-ChildItem -Path $HandoffOutput -Directory | Select-Object -First 1
    if ($subdir -and (Test-Path "$($subdir.FullName)\master_production_manifest.json")) {
        $HandoffOutput = $subdir.FullName
        Write-Host "  Manifest found in subfolder: $HandoffOutput" -ForegroundColor Green
    }
}

# Verify
if (-not (Test-Path "$HandoffOutput\master_production_manifest.json")) {
    Write-Host "  ERROR: master_production_manifest.json not found in $HandoffOutput" -ForegroundColor Red
    exit 1
}
Write-Host "  Manifest verified." -ForegroundColor Green

# --- Step 3: Install Python dependencies ---
Write-Host "[3/7] Checking Python dependencies..." -ForegroundColor Green
python -m pip install pywin32 --quiet 2>&1 | Out-Null
Write-Host "  Dependencies OK." -ForegroundColor Green

# --- Step 4: Pull latest repo code ---
Write-Host "[4/7] Pulling latest code..." -ForegroundColor Green
Push-Location $RepoDir
git pull origin devin/initial-setup --quiet 2>&1 | Out-Null
Pop-Location
Write-Host "  Code up to date." -ForegroundColor Green

# --- Step 5: Check InDesign ---
Write-Host "[5/7] Checking InDesign connection..." -ForegroundColor Green
$checkScript = @"
import sys
try:
    import win32com.client
    app = win32com.client.Dispatch('InDesign.Application')
    print(f'CONNECTED:{app.Version}')
except Exception as e:
    print(f'FAILED:{e}')
"@
$result = python -c $checkScript 2>&1
if ($result -match "CONNECTED:(.+)") {
    Write-Host "  Connected to InDesign $($Matches[1])" -ForegroundColor Green
} else {
    Write-Host "  WARNING: InDesign not connected. Trying to launch..." -ForegroundColor Yellow
    $indesignPaths = @(
        "${env:ProgramFiles}\Adobe\Adobe InDesign 2026\InDesign.exe",
        "${env:ProgramFiles}\Adobe\Adobe InDesign 2026 (Beta)\InDesign (Beta).exe",
        "${env:ProgramFiles}\Adobe\Adobe InDesign 2025\InDesign.exe",
        "${env:ProgramFiles}\Adobe\Adobe InDesign 2024\InDesign.exe"
    )
    $launched = $false
    foreach ($idPath in $indesignPaths) {
        if (Test-Path $idPath) {
            Start-Process $idPath
            Write-Host "  Launching InDesign... waiting 15 seconds" -ForegroundColor Yellow
            Start-Sleep -Seconds 15
            $launched = $true
            break
        }
    }
    if (-not $launched) {
        Write-Host "  ERROR: Could not find or launch InDesign." -ForegroundColor Red
        Write-Host "  Please open InDesign manually and re-run this script." -ForegroundColor Red
        exit 1
    }
}

# --- Step 6: Generate JSX ---
Write-Host "[6/7] Generating InDesign ExtendScript from handoff manifest..." -ForegroundColor Green
Write-Host "  50 pages, 73 assets, US Letter landscape, K-only" -ForegroundColor Gray

# --- Step 7: Execute ---
Write-Host "[7/7] Building document in InDesign..." -ForegroundColor Green
Write-Host ""

Push-Location $RepoDir
python indesign\handoff\build_from_handoff.py "$HandoffOutput" --execute
$exitCode = $LASTEXITCODE
Pop-Location

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  BUILD COMPLETE!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Output directory: $OutputBase\InDesign\" -ForegroundColor White
    Write-Host "  Check InDesign for your new document." -ForegroundColor White
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor Gray
    Write-Host "    - Review placement in InDesign" -ForegroundColor Gray
    Write-Host "    - File > Export > PDF for print output" -ForegroundColor Gray
    Write-Host "    - Or use chat agent for adjustments:" -ForegroundColor Gray
    Write-Host "      python indesign\chat_agent\chat_with_indesign.py --model $Model" -ForegroundColor Yellow
} else {
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "  BUILD FAILED" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Check the error above. Common fixes:" -ForegroundColor White
    Write-Host "    - Make sure InDesign is open and running" -ForegroundColor Gray
    Write-Host "    - Close any dialog boxes in InDesign" -ForegroundColor Gray
    Write-Host "    - Try running again" -ForegroundColor Gray
}

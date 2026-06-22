# Production Automation — Windows Setup Script
# Run this once after cloning the repo to a LOCAL path (not OneDrive!)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Production Automation Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check we're not on OneDrive
$currentPath = (Get-Location).Path
if ($currentPath -match "OneDrive") {
    Write-Host "ERROR: You are running from a OneDrive path!" -ForegroundColor Red
    Write-Host "Move this repo to a local path like: C:\Users\$env:USERNAME\production-automation\" -ForegroundColor Yellow
    Write-Host "Run: Move-Item `"$currentPath`" `"C:\Users\$env:USERNAME\production-automation`"" -ForegroundColor Yellow
    exit 1
}

# Install Python dependencies
Write-Host "[1/4] Installing Python packages..." -ForegroundColor Green
pip install ollama pywin32 mcp pillow 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  pip install failed. Trying with full path..." -ForegroundColor Yellow
    & "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m pip install ollama pywin32 mcp pillow
}
Write-Host "  Done." -ForegroundColor Green

# Check Ollama
Write-Host "[2/4] Checking Ollama..." -ForegroundColor Green
$ollamaPath = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaPath) {
    Write-Host "  Ollama found at: $($ollamaPath.Source)" -ForegroundColor Green
    $models = ollama list 2>&1
    Write-Host "  Models available:" -ForegroundColor Green
    Write-Host $models
} else {
    Write-Host "  Ollama not found. Install from https://ollama.ai" -ForegroundColor Yellow
}

# Check InDesign COM
Write-Host "[3/4] Checking InDesign COM registration..." -ForegroundColor Green
$checkScript = @"
import sys
try:
    import win32com.client
    app = win32com.client.Dispatch('InDesign.Application')
    print(f'  Connected to InDesign {app.Version}')
except Exception as e:
    print(f'  Not connected: {e}')
    print('  Make sure InDesign is running.')
"@
python -c $checkScript 2>&1

# Register MCP server with Claude Code
Write-Host "[4/4] Registering MCP server with Claude Code..." -ForegroundColor Green
$configDir = "$env:APPDATA\Claude"
if (!(Test-Path $configDir)) { New-Item -ItemType Directory -Path $configDir | Out-Null }

$serverPath = "$currentPath\indesign\mcp_server\indesign_mcp_server.py" -replace '\\', '/'
$config = @"
{
  "mcpServers": {
    "indesign": {
      "command": "python",
      "args": ["$serverPath"]
    }
  }
}
"@
$config | Out-File "$configDir\claude_desktop_config.json" -Encoding UTF8
Write-Host "  Claude Code config written to: $configDir\claude_desktop_config.json" -ForegroundColor Green

# Create output directory
$outputDir = "$env:USERPROFILE\Production-Automation-Output\InDesign"
if (!(Test-Path $outputDir)) { New-Item -ItemType Directory -Path $outputDir | Out-Null }
Write-Host ""
Write-Host "  Output directory: $outputDir" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To chat with InDesign (unlimited, local):" -ForegroundColor White
Write-Host "  python indesign\chat_agent\chat_with_indesign.py --model qwen3-coder:30b" -ForegroundColor Yellow
Write-Host ""
Write-Host "To use with Claude Code:" -ForegroundColor White
Write-Host "  Restart Claude Code — InDesign tools are auto-registered." -ForegroundColor Yellow
Write-Host ""

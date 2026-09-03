[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$Browser = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $Browser) {
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        & (Join-Path $PSScriptRoot "setup_windows.ps1")
    }
    if (Test-Path $VenvPython) {
        $Browser = (& $VenvPython -c "from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); x=Path(p.chromium.executable_path); print(x if x.exists() else ''); p.stop()" 2>$null | Select-Object -Last 1)
    }
}

if (-not $Browser -or -not (Test-Path $Browser)) {
    throw "找不到 Chrome、Edge 或 Playwright Chromium。请先运行 Install_Windows_Dependencies.bat。"
}

$Profile = Join-Path $ProjectRoot "data\chrome_debug_profile"
New-Item -ItemType Directory -Force -Path $Profile | Out-Null
Write-Host "[browser] $Browser"
Write-Host "[profile] $Profile"
Start-Process -FilePath $Browser -ArgumentList @(
    "--remote-debugging-port=9222",
    "--remote-allow-origins=*",
    "--user-data-dir=`"$Profile`"",
    "--no-first-run",
    "--no-default-browser-check",
    "https://studio.youtube.com"
)

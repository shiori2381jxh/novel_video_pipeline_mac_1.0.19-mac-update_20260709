[CmdletBinding()]
param(
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$env:NO_PROXY = "localhost,127.0.0.1,::1"
$env:no_proxy = $env:NO_PROXY
$env:PYTHONUTF8 = "1"

function Test-PythonCommand {
    param([string]$Executable, [string[]]$Prefix = @())
    try {
        & $Executable @Prefix -c "import sys, tkinter; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-BasePython {
    if ($env:NOVEL_VIDEO_PYTHON -and (Test-Path $env:NOVEL_VIDEO_PYTHON) -and
        (Test-PythonCommand $env:NOVEL_VIDEO_PYTHON)) {
        return @{ Exe = $env:NOVEL_VIDEO_PYTHON; Prefix = @() }
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @("-3.12", "-3.11", "-3.10")) {
            if (Test-PythonCommand $launcher.Source @($version)) {
                return @{ Exe = $launcher.Source; Prefix = @($version) }
            }
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python -and (Test-PythonCommand $python.Source)) {
        return @{ Exe = $python.Source; Prefix = @() }
    }

    foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )) {
        if ((Test-Path $candidate) -and (Test-PythonCommand $candidate)) {
            return @{ Exe = $candidate; Prefix = @() }
        }
    }
    return $null
}

Write-Host "[setup] Project: $ProjectRoot"
$Python = Find-BasePython
if (-not $Python) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "找不到 Python 3.10+（需要 Tkinter），并且系统没有 winget。请从 python.org 安装 64 位 Python 3.12。"
    }
    Write-Host "[setup] 未找到可用 Python，正在通过 winget 安装 Python 3.12..."
    & $winget.Source install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget 安装 Python 3.12 失败，错误码：$LASTEXITCODE"
    }
    $Python = Find-BasePython
    if (-not $Python) {
        throw "Python 已安装，但当前窗口尚未找到它。请关闭窗口后重新运行安装程序。"
    }
}

$PythonVersion = & $Python.Exe @($Python.Prefix) -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
Write-Host "[setup] Python: $PythonVersion ($($Python.Exe) $($Python.Prefix -join ' '))"

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if ($Rebuild -and (Test-Path (Join-Path $ProjectRoot ".venv"))) {
    Write-Host "[setup] 正在重建 .venv..."
    Remove-Item -LiteralPath (Join-Path $ProjectRoot ".venv") -Recurse -Force
}
if (-not (Test-Path $VenvPython)) {
    Write-Host "[setup] 正在创建 .venv..."
    & $Python.Exe @($Python.Prefix) -m venv ".venv"
    if ($LASTEXITCODE -ne 0) { throw "创建 .venv 失败。" }
}

& $VenvPython -c "import tkinter"
if ($LASTEXITCODE -ne 0) { throw "当前 Python 的 Tkinter 不可用。请安装 python.org 官方 64 位 Python 3.12。" }

Write-Host "[setup] 正在安装 Python 依赖..."
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip wheel
if ($LASTEXITCODE -ne 0) { throw "pip/wheel 升级失败。" }
& $VenvPython -m pip install --disable-pip-version-check -r "requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "requirements.txt 安装失败。" }

Write-Host "[setup] 正在准备 Playwright Chromium..."
& $VenvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Playwright Chromium 安装失败；主程序仍可运行，但 YouTube 上传需要 Chrome/Edge。"
}

Write-Host "[setup] 正在检测 FFmpeg、浏览器和上传组件..."
& $VenvPython -m app.dependency_manager --ensure
if ($LASTEXITCODE -ne 0) {
    Write-Warning "部分可选依赖尚未就绪。可启动 GUI 后在“依赖检测”中重试。"
}

Write-Host "[setup] Windows 运行环境已就绪。"

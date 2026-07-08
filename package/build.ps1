# GankAIGC - Windows 构建脚本
# 用于在 Windows 上构建可执行文件

$ErrorActionPreference = "Stop"

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败: $Step (exit code: $LASTEXITCODE)"
    }
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "GankAIGC - Windows 构建脚本" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$BuildCacheRoot = Join-Path $env:LOCALAPPDATA "GankAIGC"
New-Item -ItemType Directory -Force -Path $BuildCacheRoot | Out-Null

# 检查 Python
Write-Host ""
Write-Host "1. 检查 Python 环境..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host $pythonVersion -ForegroundColor Green
    $pythonVersionCheck = python -c "import sys; raise SystemExit(0 if (3, 9) <= sys.version_info[:2] < (3, 13) else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "错误: 当前打包脚本要求 Python 3.9 - 3.12。请切换到 Python 3.11/3.12 后重试。" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "错误: 未找到可用的 Python 3.9 - 3.12，请先安装或切换环境。" -ForegroundColor Red
    exit 1
}

# 检查 Node.js
Write-Host ""
Write-Host "2. 检查 Node.js 环境..." -ForegroundColor Yellow
try {
    $nodeVersion = node --version 2>&1
    Write-Host $nodeVersion -ForegroundColor Green
} catch {
    Write-Host "错误: 未找到 Node.js，请先安装 Node.js 18+" -ForegroundColor Red
    exit 1
}

# 创建 Windows 专用虚拟环境并安装依赖
Write-Host ""
Write-Host "3. 安装后端依赖..." -ForegroundColor Yellow
$VenvDir = Join-Path $BuildCacheRoot "build-venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvUsable = $false
if (Test-Path $VenvPython) {
    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $VenvPython -m pip --version *> $null
        $VenvUsable = ($LASTEXITCODE -eq 0)
    } catch {
        $VenvUsable = $false
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
}
if (-not $VenvUsable) {
    if (Test-Path $VenvDir) {
        Write-Host "检测到不可用的 Windows 虚拟环境目录，正在重建：$VenvDir" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $VenvDir
    }
    python -m venv $VenvDir
    Assert-LastExitCode "python -m venv $VenvDir"
    & $VenvPython -m ensurepip --upgrade
    Assert-LastExitCode "$VenvPython -m ensurepip --upgrade"
}
& $VenvPython -m pip install --upgrade pip
Assert-LastExitCode "$VenvPython -m pip install --upgrade pip"
& $VenvPython -m pip install -r requirements.txt
Assert-LastExitCode "$VenvPython -m pip install -r requirements.txt"

# 构建前端
Write-Host ""
Write-Host "4. 构建前端..." -ForegroundColor Yellow
$FrontendSource = Join-Path $ScriptDir "frontend"
$FrontendBuildDir = Join-Path $BuildCacheRoot "frontend-build"
if (Test-Path $FrontendBuildDir) {
    Remove-Item -Recurse -Force $FrontendBuildDir
}
New-Item -ItemType Directory -Force -Path $FrontendBuildDir | Out-Null
robocopy $FrontendSource $FrontendBuildDir /MIR /XD node_modules dist .vite /NFL /NDL /NJH /NJS /NP | Out-Host
if ($LASTEXITCODE -gt 7) {
    throw "复制前端源码到 Windows 本地构建目录失败，robocopy 退出码: $LASTEXITCODE"
}
$global:LASTEXITCODE = 0
Push-Location $FrontendBuildDir
try {
    npm install
    Assert-LastExitCode "npm install"
    npm run build
    Assert-LastExitCode "npm run build"
} finally {
    Pop-Location
}

# 复制前端构建产物
Write-Host ""
Write-Host "5. 复制前端构建产物..." -ForegroundColor Yellow
$StaticDir = Join-Path $ScriptDir "static"
if (Test-Path $StaticDir) {
    Remove-Item -Recurse -Force $StaticDir
}
New-Item -ItemType Directory -Force -Path $StaticDir | Out-Null
Copy-Item -Path (Join-Path $FrontendBuildDir "dist\*") -Destination $StaticDir -Recurse -Force

# 使用 PyInstaller 打包
Write-Host ""
Write-Host "6. 使用 PyInstaller 打包..." -ForegroundColor Yellow
& $VenvPython -m PyInstaller app.spec --clean
Assert-LastExitCode "$VenvPython -m PyInstaller app.spec --clean"

if (-not (Test-Path "dist\GankAIGC.exe")) {
    throw "构建失败: dist\GankAIGC.exe 未生成"
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "构建完成!" -ForegroundColor Green
Write-Host "可执行文件位置: dist\GankAIGC.exe" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "运行方式:" -ForegroundColor Yellow
Write-Host "1. 将 dist\GankAIGC.exe 复制到任意目录"
Write-Host "2. 首次运行会自动创建 .env 配置文件"
Write-Host "3. 编辑 .env 文件，填入 API Key 等配置"
Write-Host "4. 再次运行程序，将自动打开浏览器"
Write-Host ""

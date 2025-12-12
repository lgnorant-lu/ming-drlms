# DRLMS 环境变量加载脚本 (PowerShell)
# 使用方法: . .\scripts\load-env.ps1 [-File .env.local]

param(
    [string]$File = ".env.local"
)

$ErrorActionPreference = "Stop"

# 查找环境文件
$envFile = $null
$searchPaths = @($File, ".env.local", ".env.win", ".env")

foreach ($path in $searchPaths) {
    if (Test-Path $path) {
        $envFile = $path
        break
    }
}

if (-not $envFile) {
    Write-Host "[WARN] No env file found. Searched: $($searchPaths -join ', ')" -ForegroundColor Yellow
    Write-Host "[INFO] Using default development settings..." -ForegroundColor Cyan
    
    # 设置开发默认值
    $env:DRLMS_BACKEND = "mp2"
    $env:DRLMS_MP2_HOST = "127.0.0.1"
    $env:DRLMS_MP2_PORT = "15035"
    $env:DRLMS_RELAY_BASE_URL = "http://127.0.0.1:15019"
    $env:DRLMS_LOG_LEVEL = "DEBUG"
    $env:DRLMS_UPDATE_CHECK = "0"
    $env:MING_DRLMS_CONFIG_DIR = "$PWD\.drlms"
    
    Write-Host "[OK] Default env vars set" -ForegroundColor Green
    return
}

Write-Host "[INFO] Loading env from: $envFile" -ForegroundColor Cyan

$count = 0
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    # 跳过空行和注释
    if ($line -and -not $line.StartsWith('#')) {
        if ($line -match '^([^#=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            # 移除引号
            if ($value.StartsWith('"') -and $value.EndsWith('"')) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            [System.Environment]::SetEnvironmentVariable($key, $value)
            $count++
        }
    }
}

Write-Host "[OK] Loaded $count environment variables" -ForegroundColor Green

# 自动探测 Windows 构建目录并设置 DRLMS_SIGNAL_PREFIX
if (-not $env:DRLMS_SIGNAL_PREFIX) {
    $candidates = @(
        "$PWD\build_win_ninja_x64",
        "$PWD\build_win",
        "$PWD\build"
    )
    foreach ($dir in $candidates) {
        $prefix = Join-Path $dir "_deps\signal-install"
        $dll = Join-Path $prefix "bin\signal-protocol-c.dll"
        if (Test-Path $dll) {
            $env:DRLMS_SIGNAL_PREFIX = $prefix
            Write-Host "[load-env] Auto-detected DRLMS_SIGNAL_PREFIX = $prefix" -ForegroundColor Green
            break
        }
    }
    if (-not $env:DRLMS_SIGNAL_PREFIX) {
        Write-Host "[load-env] WARNING: No signal-install with DLL found in build_win*/build/" -ForegroundColor Yellow
        Write-Host "           Run C build in VS 2026 Developer Command Prompt first," -ForegroundColor Yellow
        Write-Host "           or set DRLMS_SIGNAL_PREFIX manually." -ForegroundColor Yellow
    }
}

# 自动设置 DRLMS_DATA_DIR（如未设置）
if (-not $env:DRLMS_DATA_DIR) {
    $env:DRLMS_DATA_DIR = "$PWD\server_files"
    Write-Host "[load-env] Auto-set DRLMS_DATA_DIR = $env:DRLMS_DATA_DIR" -ForegroundColor Green
    # 确保目录存在
    if (-not (Test-Path $env:DRLMS_DATA_DIR)) {
        New-Item -ItemType Directory -Path $env:DRLMS_DATA_DIR -Force | Out-Null
    }
}

# 显示关键变量
Write-Host ""
Write-Host "Key settings:" -ForegroundColor Cyan
Write-Host "  DRLMS_BACKEND         = $env:DRLMS_BACKEND"
Write-Host "  DRLMS_MP2_HOST        = $env:DRLMS_MP2_HOST"
Write-Host "  DRLMS_MP2_PORT        = $env:DRLMS_MP2_PORT"
Write-Host "  DRLMS_RELAY_BASE_URL  = $env:DRLMS_RELAY_BASE_URL"
Write-Host "  DRLMS_LOG_LEVEL       = $env:DRLMS_LOG_LEVEL"
Write-Host "  MING_DRLMS_CONFIG_DIR = $env:MING_DRLMS_CONFIG_DIR"
Write-Host "  DRLMS_DATA_DIR        = $env:DRLMS_DATA_DIR"
Write-Host "  DRLMS_SIGNAL_PREFIX   = $env:DRLMS_SIGNAL_PREFIX"
Write-Host "  DRLMS_MP2_ACCEPT_ANY  = $(if ($env:DRLMS_MP2_ACCEPT_ANY) { $env:DRLMS_MP2_ACCEPT_ANY } else { '0' })"

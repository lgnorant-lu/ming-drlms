param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Add-ToEnv($key, $value) {
    Add-Content -Path $Env:GITHUB_ENV -Value "${key}=${value}"
    Set-Item -Path "Env:${key}" -Value $value
}

$cacheRoot = Join-Path $Env:VCPKG_ROOT 'installed/x64-windows'
$buildRoot = Join-Path $Env:GITHUB_WORKSPACE 'build/vcpkg_installed/x64-windows'
$opensslRoot = $null
if (Test-Path $buildRoot) {
    $opensslRoot = $buildRoot
    Write-Host "Using build-time OpenSSL root: $opensslRoot"
} elseif (Test-Path $cacheRoot) {
    $opensslRoot = $cacheRoot
    Write-Host "Using cached OpenSSL root: $opensslRoot"
}

if (-not $opensslRoot) {
    Write-Warning "OpenSSL root not found"
} else {
    Add-ToEnv 'OPENSSL_ROOT_DIR' $opensslRoot
}

if ($Env:CI_DEBUG -eq '1') {
    Write-Host '=== VCPKG OPENSSL BIN INFO ==='
    $opensslBin = Join-Path $opensslRoot 'bin'
    if (Test-Path $opensslBin) {
        Get-ChildItem $opensslBin | Select-Object Name, Length | Format-Table -AutoSize
    }
    Write-Host '=== END DEBUG ==='
}

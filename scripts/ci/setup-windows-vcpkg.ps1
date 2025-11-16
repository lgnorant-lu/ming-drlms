param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$customRoot = if ($Env:VCPKG_ROOT) { $Env:VCPKG_ROOT } else { Join-Path $Env:RUNNER_TEMP 'vcpkg' }
$binaryCache = if ($Env:VCPKG_DEFAULT_BINARY_CACHE) { $Env:VCPKG_DEFAULT_BINARY_CACHE } else { Join-Path $Env:RUNNER_TEMP 'vcpkg-binary-cache' }
if (-not (Test-Path $binaryCache)) {
    New-Item -ItemType Directory -Path $binaryCache | Out-Null
}
if (-not (Test-Path $customRoot)) {
    New-Item -ItemType Directory -Path $customRoot | Out-Null
}

function Add-ToEnv($key, $value) {
    Add-Content -Path $Env:GITHUB_ENV -Value "${key}=${value}"
    Set-Item -Path "Env:${key}" -Value $value
}

Add-ToEnv 'VCPKG_ROOT' $customRoot
Add-ToEnv 'CMAKE_TOOLCHAIN_FILE' (Join-Path $customRoot 'scripts/buildsystems/vcpkg.cmake')
Add-ToEnv 'VCPKG_TARGET_TRIPLET' 'x64-windows'
Add-ToEnv 'VCPKG_DEFAULT_BINARY_CACHE' $binaryCache
Add-ToEnv 'VCPKG_BINARY_SOURCES' "clear;files,$binaryCache,readwrite"

$desiredVersion = '2025.10.17'
if (-not (Test-Path (Join-Path $customRoot '.git'))) {
    git clone --depth 1 --branch $desiredVersion https://github.com/microsoft/vcpkg.git $customRoot
} else {
    Push-Location $customRoot
    $currentTag = git describe --tags --abbrev=0 2>$null
    if ($currentTag -ne $desiredVersion) {
        git fetch --depth 1 origin tag $desiredVersion
        git checkout $desiredVersion
    }
    Pop-Location
}
& (Join-Path $customRoot 'bootstrap-vcpkg.bat')
Write-Host "vcpkg version: $(& "$customRoot\vcpkg.exe" version)"

"Installing manifest dependencies..." | Write-Host
$manifestFile = Join-Path $Env:GITHUB_WORKSPACE 'vcpkg.json'
& "$customRoot\vcpkg.exe" install --triplet x64-windows --x-manifest-root=$Env:GITHUB_WORKSPACE --recurse

if ($Env:CI_DEBUG -eq '1') {
    Write-Host '=== VCPKG INSTALLED CONTENTS (partial) ==='
    reg list $customRoot &> $null
}

param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    choco install cmake --installargs 'ADD_CMAKE_TO_PATH=System' --no-progress --yes
}
$cmakeBin = 'C:\Program Files\CMake\bin'
if (Test-Path $cmakeBin) {
    Add-Content -Path $Env:GITHUB_PATH -Value $cmakeBin
    Write-Host "Added $cmakeBin to PATH"
}
cmake --version

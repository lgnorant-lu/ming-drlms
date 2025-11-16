param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($Env:CI_DEBUG -ne '1') {
    Write-Host 'Skipping Windows diagnostics (CI_DEBUG!=1)'
    return
}

$signalDll = Join-Path $Env:DRLMS_SIGNAL_PREFIX 'bin/signal-protocol-c.dll'
if (Test-Path $signalDll) {
    Write-Host "Dumping dependencies of $signalDll"
    dumpbin /dependents $signalDll
}
$pycache = Join-Path $Env:GITHUB_WORKSPACE 'src/ming_drlms/core/__pycache__'
if (Test-Path $pycache) {
    Get-ChildItem $pycache -Filter '_cffi__*.pyd' -File | ForEach-Object {
        Write-Host "Dumping dependencies for $($_.FullName)"
        dumpbin /dependents $_.FullName
    }
}
Write-Host 'PATH snapshot:'
$Env:PATH -split ';' | Where-Object { $_ } | ForEach-Object { Write-Host "- $_" }

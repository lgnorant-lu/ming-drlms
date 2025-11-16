param()

function Set-CommonEnv {
    $root = Resolve-Path -Path "$PSScriptRoot/.."
    $env:DRLMS_SIGNAL_PREFIX = "$root/build/_deps/signal-install"
    $env:QT_QPA_PLATFORM = 'offscreen'
    if (-not (${env:DRLMS_UPDATE_CHECK})) {
        $env:DRLMS_UPDATE_CHECK = '0'
    }
}

Set-CommonEnv

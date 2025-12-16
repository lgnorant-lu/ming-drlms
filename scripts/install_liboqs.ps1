
# scripts/install_liboqs.ps1
# Automates building liboqs for Windows, targeting MSVC with robust detection.

$ErrorActionPreference = "Stop"

$WORK_DIR = "$PSScriptRoot\..\build_win\_deps"
$INSTALL_DIR = "$PSScriptRoot\..\build_win\_deps\liboqs-install"
$REPO_URL = "https://github.com/open-quantum-safe/liboqs.git"

# 1. Prepare Directories
Write-Host "[+] Preparing build directories..." -ForegroundColor Green
if (!(Test-Path $WORK_DIR)) { New-Item -ItemType Directory -Path $WORK_DIR | Out-Null }
if (Test-Path $INSTALL_DIR) { Remove-Item -Recurse -Force $INSTALL_DIR }

# 2. Clone Repository
Set-Location $WORK_DIR
if (!(Test-Path "liboqs")) {
    Write-Host "[+] Cloning liboqs..." -ForegroundColor Green
    git clone --depth 1 --branch main $REPO_URL liboqs
}
else {
    Write-Host "[+] liboqs already cloned, pulling latest..." -ForegroundColor Yellow
    Set-Location "liboqs"
    git pull
    Set-Location ..
}

# 2.5 Ensure MSVC Environment
if (!(Get-Command "cl.exe" -ErrorAction SilentlyContinue)) {
    Write-Host "[!] cl.exe not found in PATH." -ForegroundColor Yellow
    
    # 1. Try vswhere (standard method)
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $vsPath = $null
    
    if (Test-Path $vswhere) {
        # Get path to latest VS with VC++ tools
        # Using -products * to cover Community, Professional, Enterprise, BuildTools
        $vsPath = & $vswhere -latest -products "*" -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        
        # If bare string returned, trim whitespace
        if ($vsPath) { $vsPath = $vsPath.Trim() }
    }
    
    # 2. Check for vcvars64.bat in discovered path
    $vcvars = $null
    if ($vsPath) {
        $vcvars = "$vsPath\VC\Auxiliary\Build\vcvars64.bat"
    }
    else {
        # 3. Fallback to hardcoded paths if vswhere failed or returned nothing
        $StandardPaths = @(
            "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
            "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat",
            "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat",
            "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat",
            "C:\Program Files (x86)\Microsoft Visual Studio\2019\Enterprise\VC\Auxiliary\Build\vcvars64.bat",
            "C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\VC\Auxiliary\Build\vcvars64.bat"
        )
        foreach ($p in $StandardPaths) {
            if (Test-Path $p) { $vcvars = $p; break }
        }
    }

    if ($vcvars -and (Test-Path $vcvars)) {
        Write-Host "[+] Loading MSVC environment from: $vcvars" -ForegroundColor Green
        
        # Capture environment changes from batch file
        cmd.exe /c "call `"$vcvars`" && set > env.tmp"
        Get-Content env.tmp | ForEach-Object {
            if ($_ -match "^(.*?)=(.*)$") {
                Set-Content "env:\$($matches[1])" $matches[2]
            }
        }
        Remove-Item env.tmp
    }
    else {
        Write-Host "[ERROR] Could not find Visual Studio 2019/2022 installation via vswhere or standard paths." -ForegroundColor Red
        Write-Host "       Please manually run 'x64 Native Tools Command Prompt' and try again."
        exit 1
    }
}

# 3. Configure CMake
Write-Host "[+] Configuring CMake..." -ForegroundColor Green
Set-Location "liboqs"
# CLEANUP: Remove old build dir to prevent NMake/Ninja conflicts
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

# Enable shared libs (DLL) is crucial for Python wrapper
# MSVC: Use default flags (CMake auto-detects cl.exe when in Dev Prompt)
# Disable tests to avoid linker errors on specific algos (we just need the DLL)
cmake -S . -B build -G "Ninja" -DBUILD_SHARED_LIBS=ON -DCMAKE_INSTALL_PREFIX="$INSTALL_DIR" -DOQS_USE_OPENSSL=OFF -DOQS_BUILD_TESTS=OFF

# 4. Build and Install
Write-Host "[+] Building liboqs (Release)..." -ForegroundColor Green

# Step A: Build ONLY the library target (bypassing tests/docs)
cmake --build build --config Release --target oqs

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Build failed." -ForegroundColor Red
    exit 1
}

# Step B: Install (or manual copy if install triggers tests)
# Try standard install first
Write-Host "[+] Installing..." -ForegroundColor Green
cmake --build build --config Release --target install

# 5. Verify Output
if (Test-Path "$INSTALL_DIR\bin\oqs.dll") {
    Write-Host "`n[SUCCESS] liboqs installed to: $INSTALL_DIR" -ForegroundColor Green
    Write-Host "[INFO] To use it, you MUST set these environment variables before running Python:"
    Write-Host "       `$env:PATH += `";$INSTALL_DIR\bin`""
    Write-Host "       `$env:LIBOQS_DIR = `"$INSTALL_DIR`""
}
else {
    # Fallback: Manual Copy if install failed but build succeeded
    if (Test-Path "build\bin\oqs.dll") {
        Write-Host "[+] 'install' target failed but oqs.dll exists. Manually copying..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Path "$INSTALL_DIR\bin" -Force | Out-Null
        Copy-Item "build\bin\oqs.dll" "$INSTALL_DIR\bin"
        
        Write-Host "`n[SUCCESS] liboqs installed (manual copy) to: $INSTALL_DIR" -ForegroundColor Green
        Write-Host "[INFO] To use it, you MUST set these environment variables before running Python:"
        Write-Host "       `$env:PATH += `";$INSTALL_DIR\bin`""
    }
    else {
        Write-Host "`n[ERROR] oqs.dll not found in build or install directory!" -ForegroundColor Red
        exit 1
    }
}

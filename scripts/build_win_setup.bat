@echo off
setlocal enabledelayedexpansion

echo [INFO] Starting Windows MSVC Build Setup...

:: ==========================================
:: 0. Ensure we are in project root
:: ==========================================
if exist "CMakeLists.txt" (
    echo [INFO] CMakeLists.txt found in current directory.
) else (
    if exist "..\CMakeLists.txt" (
        echo [INFO] CMakeLists.txt found in parent directory. Switching context...
        cd ..
    ) else (
        echo [ERROR] Cannot find CMakeLists.txt. Please run this from project root.
        exit /b 1
    )
)

:: ==========================================
:: 1. Find VsDevCmd.bat
:: ==========================================
set "VS_DEV_CMD="

:: Method A: Try vswhere
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find **\VsDevCmd.bat`) do (
        set "VS_DEV_CMD=%%i"
    )
)

:: Method B: Try User's Known Path (D:\Coding\vs_BuildTools)
if not defined VS_DEV_CMD (
    if exist "D:\Coding\vs_BuildTools\Common7\Tools\VsDevCmd.bat" (
        set "VS_DEV_CMD=D:\Coding\vs_BuildTools\Common7\Tools\VsDevCmd.bat"
    )
)

:: Method C: Try Standard Paths
if not defined VS_DEV_CMD (
    if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" (
        set "VS_DEV_CMD=C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
    ) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\Common7\Tools\VsDevCmd.bat" (
        set "VS_DEV_CMD=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\Common7\Tools\VsDevCmd.bat"
    ) else if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" (
        set "VS_DEV_CMD=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"
    )
)

if not defined VS_DEV_CMD (
    echo [ERROR] Could not find VsDevCmd.bat.
    echo [HINT] Please install Visual Studio 2022 Build Tools with "Desktop development with C++".
    exit /b 1
)

echo [INFO] Found VS Dev Command Script: "%VS_DEV_CMD%"
echo [INFO] Activating MSVC Environment...

:: ==========================================
:: 2. Activate MSVC Environment
:: ==========================================
call "%VS_DEV_CMD%" -arch=x64 >nul 2>&1

where cl.exe >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] cl.exe is not in PATH after activation.
    exit /b 1
)

echo [SUCCESS] MSVC Environment Activated!
cl.exe 2>&1 | findstr "Microsoft"

:: ==========================================
:: 3. Check for Pre-generated Protobuf Files
:: ==========================================
if not exist "src\generated\schema\v2\common.pb-c.c" (
    echo [WARNING] Pre-generated protobuf-c files not found in src\generated\schema\v2.
    echo [INFO] Windows build requires these files because protoc-c is missing.
    echo [INFO] Please run the build in WSL first to generate them, then copy to src\generated\schema\v2.
)

:: ==========================================
:: 4. Configure and Build (Ninja)
:: ==========================================
echo.
echo [INFO] Configuring CMake (VS 2022 Generator)...

if exist "build\win-msvc\CMakeCache.txt" del "build\win-msvc\CMakeCache.txt"

cmake -S . -B build/win-msvc -G "Visual Studio 17 2022" -A x64
if %errorlevel% neq 0 goto :error

echo.
echo [INFO] Building Project...
cmake --build build/win-msvc --config Release
if %errorlevel% neq 0 goto :error

:: ==========================================
:: 5. Deploy DLLs
:: ==========================================
echo.
echo [INFO] Deploying DLLs...

:: Copy to src/ming_drlms/core/lib (creating if needed)
if not exist "src\ming_drlms\core\lib" mkdir "src\ming_drlms\core\lib"
copy /Y "build\win-msvc\_deps\signal-install\bin\signal-protocol-c.dll" "src\ming_drlms\core\lib\" >nul

:: Also keep the old path just in case
if not exist "src\core\lib" mkdir "src\core\lib"
copy /Y "build\win-msvc\_deps\signal-install\bin\signal-protocol-c.dll" "src\core\lib\" >nul

if %errorlevel% neq 0 (
    echo [WARNING] DLL copy failed.
) else (
    echo [SUCCESS] DLL deployed.
)

echo.
echo [INFO] Build setup complete.
goto :eof

:error
echo.
echo [ERROR] Build failed. See errors above.
exit /b 1

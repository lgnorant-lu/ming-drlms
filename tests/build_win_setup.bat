@echo on
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64
if errorlevel 1 goto :error
cd /d %~dp0
cmake -S . -B build-win -G "NMake Makefiles" -DCMAKE_TOOLCHAIN_FILE=D:/Coding/vcpkg/scripts/buildsystems/vcpkg.cmake -DVCPKG_TARGET_TRIPLET=x64-windows -DCMAKE_INSTALL_PREFIX=%~dp0dist-win
if errorlevel 1 goto :error
cmake --build build-win --target install
if errorlevel 1 goto :error
echo Build and install completed.
exit /b 0
:error
echo Build failed with error %errorlevel%.
exit /b %errorlevel%

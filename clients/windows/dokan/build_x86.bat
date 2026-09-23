@echo off
setlocal
set "DOKAN_DIR=%ProgramFiles%\Dokan\DokanLibrary"
if not exist "%DOKAN_DIR%\dokan2.lib" (
  echo ERROR: Could not find Dokan at:
  echo %DOKAN_DIR%
  echo Install the x86 Dokany package, then edit DOKAN_DIR in this file if needed.
  pause
  exit /b 1
)
where cl >nul 2>nul
if errorlevel 1 (
  echo ERROR: cl.exe was not found.
  echo Open a Visual Studio Developer Command Prompt for x86, then run this file.
  pause
  exit /b 2
)
cl /nologo /EHsc /std:c++17 /O2 /I"%DOKAN_DIR%" ramlink_dokan.cpp /link /LIBPATH:"%DOKAN_DIR%" dokan2.lib Ws2_32.lib /OUT:ramlink_dokan.exe
if errorlevel 1 (
  echo BUILD FAILED
  pause
  exit /b 3
)
echo BUILD OK: ramlink_dokan.exe
echo.
echo The Dokan adapter now talks to the local RAM-Link service:
echo   127.0.0.1:19080
echo.
echo Start the Python service first, for example:
echo   python ramlink_memory_service.py PHONE_IP --mb 256
echo.
echo Then mount:
echo   ramlink_dokan.exe R:
echo.
pause

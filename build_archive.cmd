@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist ".conda\python.exe" (
    set "PYTHON_EXE=.conda\python.exe"
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
    ) else (
        set "PYTHON_EXE=python"
    )
)

echo Building JSON and HTML...
"%PYTHON_EXE%" %PYTHON_ARGS% build_archive.py

set "BUILD_EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%BUILD_EXIT_CODE%"=="0" (
    echo Build failed. Review the message above.
    popd
    exit /b %BUILD_EXIT_CODE%
)
echo Build completed. JSON and HTML are up to date.
echo Starting local summary service...
echo.

"%PYTHON_EXE%" %PYTHON_ARGS% serve_summary.py
set "SERVER_EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %SERVER_EXIT_CODE%

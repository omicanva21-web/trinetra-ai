@echo off
setlocal enableextensions
title Trinetra AI
cd /d "%~dp0"
echo.
echo  ==========================================
echo   Trinetra AI - local prototype launcher
echo  ==========================================
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" || goto oldpython

if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/4] Creating the Python environment in backend\.venv ...
  %PY% -m venv backend\.venv || goto fail
) else (
  echo [1/4] Python environment found.
)
set "VPY=%~dp0backend\.venv\Scripts\python.exe"

if not exist "backend\.venv\core-installed-v2.txt" (
  echo [2/4] Installing packages. First run only, about 2-5 minutes ...
  "%VPY%" -m pip install --upgrade pip
  "%VPY%" -m pip install -r backend\requirements-core.txt || goto fail
  echo ok> "backend\.venv\core-installed-v2.txt"
) else (
  echo [2/4] Packages already installed.
)

if not exist "backend\.venv\speedup-v3.txt" (
  echo       Optional speed-up for Dense crowd mode: ONNX Runtime, about 15 MB ...
  "%VPY%" -m pip install "onnxruntime>=1.17" && echo ok> "backend\.venv\speedup-v3.txt"
  if not exist "backend\.venv\speedup-v3.txt" echo       Not installed - Dense crowd mode still works, about 2x slower.
)

if not exist ".env" copy ".env.example" ".env" >nul
echo [3/4] Checking the sample video ...
"%VPY%" backend\tools\get_sample_video.py

echo [4/4] Starting Trinetra. The dashboard opens in your browser by itself.
echo       Keep this window open. To stop: close it or press Ctrl+C.
"%VPY%" backend\run.py
goto end

:nopython
echo Python was not found.
echo Install Python 3.11 from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run start.bat again.
goto end

:oldpython
echo Could not run Python 3.9 or newer. The Microsoft Store "python" shortcut does not count.
echo Install Python 3.11 from https://www.python.org/downloads/ (tick "Add python.exe to PATH") and run start.bat again.
goto end

:fail
echo.
echo Something failed above. Read the last error lines, or see README section "Troubleshooting".

:end
echo.
pause

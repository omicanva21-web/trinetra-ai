@echo off
setlocal enableextensions
title Trinetra AI - install YOLO26 (optional)
cd /d "%~dp0"
if not exist "backend\.venv\Scripts\python.exe" (
  echo Run start.bat once first, then run this file.
  pause
  exit /b 1
)
echo.
echo OPTIONAL. Trinetra already tracks people with its built-in detectors.
echo This installs Ultralytics YOLO26 + ByteTrack, the most accurate option. Download: about 300 MB to 2 GB.
echo.
echo NVIDIA GPU? Before continuing, install PyTorch with CUDA into backend\.venv using the command from
echo https://pytorch.org/get-started/locally/  (Windows, Pip, Python, your CUDA version), e.g.:
echo   backend\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
echo Without a GPU just continue: the normal CPU version is installed.
echo.
pause
"backend\.venv\Scripts\python.exe" -m pip install ultralytics || goto fail
"backend\.venv\Scripts\python.exe" -c "import torch, ultralytics; print('PyTorch', torch.__version__, '| CUDA GPU available:', torch.cuda.is_available(), '| Ultralytics', ultralytics.__version__)"
echo.
echo Done. Close Trinetra and run start.bat again. Camera tiles will show "yolo26n + ByteTrack".
goto end
:fail
echo Installation failed. Nothing is lost: Trinetra keeps using its built-in detectors.
:end
pause

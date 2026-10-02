@echo off
REM Smallest build: uses a clean pip-only virtual environment (.buildenv) next to this
REM file, so numpy/scipy come from PyPI wheels (OpenBLAS) instead of conda's large MKL DLLs.
REM tbwk is installed from PyPI if possible; otherwise it is copied from jlenv.
REM Needs internet access for pip. jlenv itself is not modified.
REM Output: dist\read_nanodrop.exe

setlocal
set ENV=C:\Users\luce\AppData\Local\miniconda3\envs\jlenv
set PY=.buildenv\Scripts\python.exe
cd /d "%~dp0"

if not exist "%PY%" (
  echo === Creating build environment ===
  "%ENV%\python.exe" -m venv .buildenv || goto :fail
)

echo.
echo === Installing numpy, scipy, pyinstaller ===
"%PY%" -m pip install --upgrade numpy scipy pyinstaller || goto :fail

echo.
echo === Installing twbk-opener ===
"%PY%" -c "import tbwk" 2>nul && goto :build
"%PY%" -m pip install twbk-opener && goto :build

echo.
echo twbk-opener not available from pip - copying tbwk from jlenv instead.
if exist vendor rmdir /s /q vendor
"%ENV%\python.exe" -c "import tbwk, os, shutil; src = os.path.dirname(tbwk.__file__); print('Found tbwk at', src); shutil.copytree(src, os.path.join('vendor', 'tbwk'), ignore=shutil.ignore_patterns('__pycache__'))" || goto :fail

:build
echo.
echo === Building exe ===
set EXTRA=
if exist vendor (
  set EXTRA=--paths vendor
  set PYTHONPATH=%~dp0vendor
)
"%PY%" -m PyInstaller --onefile --console --clean --noconfirm %EXTRA% ^
  --name read_nanodrop ^
  --collect-all tbwk ^
  --exclude-module tkinter ^
  --exclude-module IPython ^
  --exclude-module notebook ^
  --exclude-module pytest ^
  --exclude-module PyQt5 ^
  --exclude-module PySide2 ^
  --exclude-module PySide6 ^
  read_nanodrop.py || goto :fail

echo.
echo Build complete: %~dp0dist\read_nanodrop.exe
pause
exit /b 0

:fail
echo.
echo Build FAILED - see the messages above.
pause
exit /b 1

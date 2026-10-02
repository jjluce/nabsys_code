@echo off
REM Builds a single-file read_nanodrop.exe from the jlenv conda environment.
REM Output: dist\read_nanodrop.exe
REM Lean version: lets PyInstaller pick only the numpy/scipy modules tbwk actually uses.

setlocal
set ENV=C:\Users\luce\AppData\Local\miniconda3\envs\jlenv
set PATH=%ENV%;%ENV%\Library\bin;%ENV%\Scripts;%PATH%

cd /d "%~dp0"

"%ENV%\python.exe" -m PyInstaller --onefile --console --clean --noconfirm ^
  --name read_nanodrop ^
  --collect-all tbwk ^
  --exclude-module tkinter ^
  --exclude-module IPython ^
  --exclude-module notebook ^
  --exclude-module pytest ^
  --exclude-module PyQt5 ^
  --exclude-module PySide2 ^
  --exclude-module PySide6 ^
  read_nanodrop.py

if errorlevel 1 (
  echo.
  echo Build FAILED.
) else (
  echo.
  echo Build complete: %~dp0dist\read_nanodrop.exe
)
pause

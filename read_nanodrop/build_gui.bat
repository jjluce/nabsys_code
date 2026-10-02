@echo off
REM Builds the window (no command line) version of the NanoDrop reader from jlenv,
REM using the same settings as the original build that worked.
REM Never overwrites: each build is numbered, e.g. dist\read_nanodrop_gui_1.exe, _2.exe, ...

setlocal
set ENV=C:\Users\luce\AppData\Local\miniconda3\envs\jlenv
set PATH=%ENV%;%ENV%\Library\bin;%ENV%\Scripts;%PATH%

cd /d "%~dp0"

set N=1
:findnum
if exist "dist\read_nanodrop_gui_%N%.exe" (set /a N+=1 & goto :findnum)
if exist "read_nanodrop_gui_%N%.spec" (set /a N+=1 & goto :findnum)
set NAME=read_nanodrop_gui_%N%
echo Building %NAME%.exe

"%ENV%\python.exe" -m PyInstaller --onefile --windowed --noconfirm ^
  --name %NAME% ^
  --collect-all tbwk ^
  --collect-submodules scipy ^
  --collect-submodules numpy ^
  read_nanodrop_gui.py

if errorlevel 1 (
  echo.
  echo Build FAILED.
) else (
  echo.
  echo Build complete: %~dp0dist\%NAME%.exe
)
pause

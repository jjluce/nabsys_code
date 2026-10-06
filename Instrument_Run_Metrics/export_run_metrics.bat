@echo off
setlocal
rem ---------------------------------------------------------------------------------------------
rem export_run_metrics.bat
rem Exports SystemMetrics, ChannelData and RunData for one sample from an instrument SQLite
rem database into three header-row CSVs named the way instrument_run_metrics.py expects:
rem     SystemMetrics_<SampleID>.csv, ChannelData_<SampleID>.csv, RunData_<SampleID>.csv
rem
rem Needs sqlite3.exe in the same folder as this .bat (or on PATH). No install required:
rem download "sqlite-tools-win-x64-....zip" from https://www.sqlite.org/download.html and copy
rem sqlite3.exe next to this file (e.g. both on a USB stick).
rem
rem Usage:
rem     export_run_metrics.bat "D:\SharedData\System\UnoHost.db" TC043_D008-02B63894w16-205B21a [output folder]
rem   or just double-click it (or drag the .db file onto it) and answer the prompts.
rem The database is opened read-only. Default output folder: exports\<SampleID> next to this .bat.
rem ---------------------------------------------------------------------------------------------

rem ---- find sqlite3.exe: next to this .bat first, then on PATH ----
set "SQLITE=%~dp0sqlite3.exe"
if exist "%SQLITE%" goto :have_sqlite
where sqlite3 >nul 2>&1
if errorlevel 1 goto :no_sqlite
set "SQLITE=sqlite3"
:have_sqlite

rem ---- inputs ----
set "DB=%~1"
set "SAMPLE=%~2"
set "OUT=%~3"
if "%DB%"=="" set /p "DB=Path to instrument database (.db): "
if defined DB set "DB=%DB:"=%"
if "%SAMPLE%"=="" set /p "SAMPLE=Sample ID: "
if "%OUT%"=="" set "OUT=%~dp0exports\%SAMPLE%"

if not exist "%DB%" (
    echo Database not found: "%DB%"
    goto :end
)
if not exist "%OUT%" mkdir "%OUT%"

set "RUN=(SELECT RunIDRecord FROM RunData WHERE SampleID = '%SAMPLE%' LIMIT 1)"

rem ---- export ----
echo Exporting %SAMPLE% ...
"%SQLITE%" -readonly "%DB%" ".headers on" ".mode csv" ^
  ".output '%OUT%\SystemMetrics_%SAMPLE%.csv'" "SELECT * FROM SystemMetrics WHERE RunIDRecord = %RUN%;" ^
  ".output '%OUT%\ChannelData_%SAMPLE%.csv'"   "SELECT * FROM ChannelData WHERE RunIDRecord = %RUN%;" ^
  ".output '%OUT%\RunData_%SAMPLE%.csv'"       "SELECT * FROM RunData WHERE SampleID = '%SAMPLE%';" ^
  ".output stdout"
if errorlevel 1 (
    echo sqlite3 reported an error - see above.
    goto :end
)

rem Row counts (header excluded) as a sanity check; 0 rows usually means a mistyped Sample ID.
for %%T in (SystemMetrics ChannelData RunData) do call :count %%T
echo Done. Files are in "%OUT%"
goto :end

rem ---- subroutine: print row count of one exported file ----
:count
set "ROWS=0"
for /f %%N in ('type "%OUT%\%1_%SAMPLE%.csv" ^| find /c /v ""') do set /a "ROWS=%%N-1"
if %ROWS% LSS 0 set "ROWS=0"
echo   %1: %ROWS% rows
goto :eof

:no_sqlite
echo sqlite3.exe not found. Put sqlite3.exe in the same folder as this .bat file:
echo   %~dp0
echo (download sqlite-tools-win-x64 from https://www.sqlite.org/download.html)

:end
if "%~2"=="" pause
endlocal

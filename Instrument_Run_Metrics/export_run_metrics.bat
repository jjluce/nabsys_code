@echo off
setlocal
rem ---------------------------------------------------------------------------------------------
rem export_run_metrics.bat
rem Exports the data instrument_run_metrics.py needs for one sample from an instrument SQLite
rem database into three header-row CSVs:
rem     SystemMetrics_<SampleID>.csv, ChannelData_<SampleID>.csv, RunData_<SampleID>.csv
rem
rem Only the columns the figures use are exported, and ChannelData is thinned to one reading per
rem channel every EVERY_SEC seconds of run time (default 60 - the same rows the overnight and
rem sequential figures keep anyway). An overnight run's ChannelData drops from ~2 GB to ~25 MB.
rem sqlite3 streams the rows straight to disk, so memory use on the instrument PC stays small.
rem Set EVERY_SEC=1 below to export every ChannelData reading (full size).
rem
rem Needs sqlite3.exe in the same folder as this .bat (or on PATH). No install required:
rem download "sqlite-tools-win-x64-....zip" from https://www.sqlite.org/download.html and copy
rem sqlite3.exe next to this file.
rem
rem Usage (e.g. from \\proton\TechDevGroup\Users\Luce\LabTools after pushd):
rem     export_run_metrics.bat "D:\SharedData\System\UnoHost.db" TC043_D008-02B63894w16-205B21a [output folder]
rem   or just double-click it (or drag the .db file onto it) and answer the prompts.
rem The database is opened read-only. Default output folder: exports\<SampleID> next to this .bat.
rem ---------------------------------------------------------------------------------------------

rem ---- settings ----
set "EVERY_SEC=60"
set "SYS_COLS=RunIDRecord, Timestamp, TotalEventRate, ActiveChannelCount, [Current(A)], [BiasVoltage(V)], [Resistance(Ohms)]"
set "CH_COLS=RunIDRecord, ChannelID, TimeStamp, ViableChannel, TotalEventRate, Baseline, SignalRMS, LevelOne"
set "RD_COLS=RunIDRecord, RunID, SampleID, SystemID, RunStartTime, ProtocolName, SettingsGroup, ReagentLot, DetectorLotNumber, DetectorWaferID, DetectorDieNumber"

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

rem ---- queries ----
set "RUN=(SELECT RunIDRecord FROM RunData WHERE SampleID = '%SAMPLE%' LIMIT 1)"
set "SYS_SQL=SELECT %SYS_COLS% FROM SystemMetrics WHERE RunIDRecord = %RUN%;"
rem ChannelData: keep rows whose whole seconds since the run's first reading are a multiple of
rem EVERY_SEC (matches the Time_sec %% 60 == 0 filter in instrument_run_metrics.py)
set "CH_SQL=SELECT %CH_COLS% FROM ChannelData WHERE RunIDRecord = %RUN% AND CAST(ROUND(TimeStamp - (SELECT MIN(TimeStamp) FROM ChannelData WHERE RunIDRecord = %RUN%)) AS INTEGER) %% %EVERY_SEC% = 0;"
set "RD_SQL=SELECT %RD_COLS% FROM RunData WHERE SampleID = '%SAMPLE%';"

rem ---- export ----
echo Exporting %SAMPLE% (ChannelData every %EVERY_SEC% s) ...
"%SQLITE%" -readonly "%DB%" ".headers on" ".mode csv" ^
  ".output '%OUT%\SystemMetrics_%SAMPLE%.csv'" "%SYS_SQL%" ^
  ".output '%OUT%\ChannelData_%SAMPLE%.csv'"   "%CH_SQL%" ^
  ".output '%OUT%\RunData_%SAMPLE%.csv'"       "%RD_SQL%" ^
  ".output stdout"
if errorlevel 1 (
    echo sqlite3 reported an error - see above.
    goto :end
)

rem Row counts (header excluded) as a sanity check; 0 rows usually means a mistyped Sample ID.
for %%T in (SystemMetrics ChannelData RunData) do call :count %%T
echo Done. Files are in "%OUT%"
goto :end

rem ---- subroutine: print row count and size of one exported file ----
:count
set "ROWS=0"
for /f %%N in ('type "%OUT%\%1_%SAMPLE%.csv" ^| find /c /v ""') do set /a "ROWS=%%N-1"
if %ROWS% LSS 0 set "ROWS=0"
for %%F in ("%OUT%\%1_%SAMPLE%.csv") do set "BYTES=%%~zF"
echo   %1: %ROWS% rows, %BYTES% bytes
goto :eof

:no_sqlite
echo sqlite3.exe not found. Put sqlite3.exe in the same folder as this .bat file:
echo   %~dp0
echo (download sqlite-tools-win-x64 from https://www.sqlite.org/download.html)

:end
if "%~2"=="" pause
endlocal

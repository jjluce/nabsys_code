@echo off
setlocal
rem ---------------------------------------------------------------------------------------------
rem export_run_metrics_avg.bat   (kept in Instrument_Run_Metrics\metric_avg_comparisons)
rem Comparison/reference only - the export in routine use is ..\export_run_metrics.bat.
rem To use it, copy it next to sqlite3.exe (e.g. \\proton\TechDevGroup\Users\Luce\LabTools).
rem Same as ..\export_run_metrics.bat, but ChannelData is AVERAGED over each minute of run time
rem instead of taking a one-reading-per-minute snapshot. Output goes to a separate folder
rem (exports_avg\<SampleID>) so the two kinds of export can be compared side by side.
rem
rem Minutes are counted from the start of each data-collection block (RunSubSetRecord: the first
rem 2-minute block, then 30-minute blocks separated by ~4-minute cleaning cycles), so no minute
rem straddles a cleaning cycle. By default the first minute of each block is kept and the last
rem minute of each block is dropped (SKIP_FIRST_MIN / SKIP_LAST_MIN below). Minutes with fewer than
rem MIN_SAMPLES readings (e.g. a dropout) are dropped too.
rem
rem Per channel and per minute:
rem   ViableChannel  TRUE if the channel was viable for more than half of that minute's readings
rem                  (exactly half = FALSE)
rem   TotalEventRate, Baseline, SignalRMS
rem                  mean over the viable readings in that minute (all readings if none were viable)
rem   LevelOne       same, but ignoring the LEVEL_ONE_SENTINEL placeholder (400; 600 before ~Nov 2025);
rem                  written as the sentinel if every reading in the minute was the placeholder
rem   TimeStamp      start of the minute (block start + n * 60 s)
rem   RunSubSetRecord, MinuteInBlock   which block / minute of the block the row is
rem   Samples        number of readings averaged
rem Block start/end times come from SystemMetrics (identical to ChannelData's), so the 2 GB
rem ChannelData table is only scanned once.
rem SystemMetrics (all 1 Hz rows) and RunData are exported exactly as in export_run_metrics.bat.
rem
rem Cost on the instrument PC (full overnight run): ~30 s CPU, ~10 MB RAM, and ~1 GB of
rem temporary files in %TEMP% while SQLite sorts readings into minutes (deleted automatically).
rem
rem Needs sqlite3.exe in the same folder as this .bat (or on PATH).
rem Usage (e.g. from \\proton\TechDevGroup\Users\Luce\LabTools after pushd):
rem     export_run_metrics_avg.bat "D:\SharedData\System\UnoHost.db" TC043_D008-02B63894w16-205B21a [output folder]
rem   or just double-click it (or drag the .db file onto it) and answer the prompts.
rem The database is opened read-only. Default output folder: exports_avg\<SampleID> next to this .bat.
rem ---------------------------------------------------------------------------------------------

rem ---- settings ----
set "SKIP_FIRST_MIN=0"
set "SKIP_LAST_MIN=1"
set "MIN_SAMPLES=30"
set "LEVEL_ONE_SENTINEL=400"
set "SYS_COLS=RunIDRecord, Timestamp, TotalEventRate, ActiveChannelCount, [Current(A)], [BiasVoltage(V)], [Resistance(Ohms)]"
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
if "%OUT%"=="" set "OUT=%~dp0exports_avg\%SAMPLE%"

if not exist "%DB%" (
    echo Database not found: "%DB%"
    goto :end
)
if not exist "%OUT%" mkdir "%OUT%"

rem ---- queries ----
set "RUN=(SELECT RunIDRecord FROM RunData WHERE SampleID = '%SAMPLE%' LIMIT 1)"
rem blocks: start time and index of the last minute of each data-collection block, from SystemMetrics
set "BLOCKS=(SELECT RunSubSetRecord AS sub, MIN(Timestamp) AS t_start, CAST((MAX(Timestamp) - MIN(Timestamp)) / 60 AS INTEGER) AS last_bin FROM SystemMetrics WHERE RunIDRecord = %RUN% GROUP BY RunSubSetRecord)"
set "SYS_SQL=SELECT %SYS_COLS% FROM SystemMetrics WHERE RunIDRecord = %RUN%;"
set "CH_SQL=SELECT RunIDRecord, ChannelID, t_start + 60 * bin AS TimeStamp, sub AS RunSubSetRecord, bin AS MinuteInBlock, CASE WHEN AVG(v) > 0.5 THEN 'TRUE' ELSE 'FALSE' END AS ViableChannel, COALESCE(AVG(CASE WHEN v THEN TotalEventRate END), AVG(TotalEventRate)) AS TotalEventRate, COALESCE(AVG(CASE WHEN v THEN Baseline END), AVG(Baseline)) AS Baseline, COALESCE(AVG(CASE WHEN v THEN SignalRMS END), AVG(SignalRMS)) AS SignalRMS, COALESCE(AVG(CASE WHEN v AND LevelOne <> %LEVEL_ONE_SENTINEL% THEN LevelOne END), AVG(CASE WHEN LevelOne <> %LEVEL_ONE_SENTINEL% THEN LevelOne END), %LEVEL_ONE_SENTINEL%) AS LevelOne, COUNT(*) AS Samples FROM (SELECT c.RunIDRecord, c.ChannelID, c.TotalEventRate, c.Baseline, c.SignalRMS, c.LevelOne, (UPPER(c.ViableChannel) = 'TRUE' OR c.ViableChannel = 1) AS v, b.sub, b.t_start, b.last_bin, CAST((c.TimeStamp - b.t_start) / 60 AS INTEGER) AS bin FROM ChannelData c JOIN %BLOCKS% b ON c.RunSubSetRecord = b.sub WHERE c.RunIDRecord = %RUN%) WHERE bin >= %SKIP_FIRST_MIN% AND bin <= last_bin - %SKIP_LAST_MIN% GROUP BY RunIDRecord, sub, ChannelID, bin HAVING COUNT(*) >= %MIN_SAMPLES%;"
set "RD_SQL=SELECT %RD_COLS% FROM RunData WHERE SampleID = '%SAMPLE%';"

rem ---- export ----
echo Exporting %SAMPLE% (ChannelData averaged per minute of each collection block; this can take a minute) ...
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

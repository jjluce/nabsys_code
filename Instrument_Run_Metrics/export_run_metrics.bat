@echo off
setlocal EnableExtensions
rem ---------------------------------------------------------------------------------------------
rem export_run_metrics.bat
rem Exports the data instrument_run_metrics.py needs for one or more samples from an instrument
rem SQLite database. Each sample gets its own folder, OUT_ROOT\<SampleID>, holding three CSVs:
rem     SystemMetrics_<SampleID>.csv, ChannelData_<SampleID>.csv, RunData_<SampleID>.csv
rem
rem Several samples are exported together in ONE pass over the database: ChannelData (the huge
rem table) is read once for all of them, so exporting 9 runs takes about as long as 1.
rem
rem Only the columns the figures use are exported, and ChannelData is thinned to one reading per
rem channel every EVERY_SEC seconds of run time (default 60 - the same rows the overnight and
rem sequential figures keep anyway). An overnight run's ChannelData drops from ~2 GB to ~25 MB.
rem
rem The CSVs are written to a local folder first (%TEMP%), then copied to the output folders,
rem so nothing on the network share is held open during the slow part of the export.
rem Samples whose output folder already has a ChannelData file are skipped.
rem
rem Run it while the instrument is idle (not collecting): the export reads the instrument's
rem database heavily and can take several minutes.
rem
rem Needs sqlite3.exe in the same folder as this .bat (or on PATH). No install required:
rem download "sqlite-tools-win-x64-....zip" from https://www.sqlite.org/download.html and copy
rem sqlite3.exe next to this file.
rem
rem Usage (e.g. from \\proton\TechDevGroup\Users\Luce\LabTools after pushd):
rem     export_run_metrics.bat "D:\SharedData\System\UnoHost.db" SampleID1 SampleID2 SampleID3 ...
rem     export_run_metrics.bat "D:\SharedData\System\UnoHost.db" samples.txt
rem         (samples.txt: one Sample ID per line; lines starting with # are ignored)
rem   or just double-click it (or drag the .db file onto it) and answer the prompts.
rem The database is opened read-only (SQLite refuses any write to it).
rem ---------------------------------------------------------------------------------------------

rem ---- settings ----
set "OUT_ROOT=run_metric_exports"
set "EVERY_SEC=60"
set "SYS_COLS=RunIDRecord, Timestamp, TotalEventRate, ActiveChannelCount, [Current(A)], [BiasVoltage(V)], [Resistance(Ohms)]"
set "CH_COLS=c.RunIDRecord, c.ChannelID, c.TimeStamp, c.ViableChannel, c.TotalEventRate, c.Baseline, c.SignalRMS, c.LevelOne"
set "RD_COLS=RunIDRecord, RunID, SampleID, SystemID, RunStartTime, ProtocolName, SettingsGroup, ReagentLot, DetectorLotNumber, DetectorWaferID, DetectorDieNumber"

set "HERE=%~dp0"
set "OUTBASE=%HERE%%OUT_ROOT%"

rem ---- find sqlite3.exe: next to this .bat first, then on PATH ----
set "SQLITE=%HERE%sqlite3.exe"
if exist "%SQLITE%" goto :have_sqlite
where sqlite3 >nul 2>&1
if errorlevel 1 goto :no_sqlite
set "SQLITE=sqlite3"
:have_sqlite

rem ---- inputs: database, then sample IDs and/or text files of sample IDs ----
set "PROMPTED="
set "DB=%~1"
if "%DB%"=="" set "PROMPTED=1"
if "%DB%"=="" set /p "DB=Path to instrument database (.db): "
if defined DB set "DB=%DB:"=%"
if not exist "%DB%" (
    echo Database not found: "%DB%"
    goto :end
)

set "IDS="
set "INLIST="
set "TYPED="
set "NIDS=0"
shift
:args
if "%~1"=="" goto :args_done
if exist "%~1" (
    for /f "usebackq eol=# tokens=1" %%S in ("%~1") do call :addid %%S
) else (
    call :addid %~1
)
shift
goto :args
:args_done
if "%NIDS%"=="0" if not defined IDS (
    set "PROMPTED=1"
    set /p "TYPED=Sample IDs (separate with spaces): "
)
if defined TYPED for %%S in (%TYPED%) do call :addid %%S
if "%NIDS%"=="0" (
    echo No samples to export.
    goto :end
)
set "INLIST=%INLIST:~1%"

rem ---- local working folder (cleared first) ----
set "WORK=%TEMP%\run_metric_export"
if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%"
for %%S in (%IDS%) do mkdir "%WORK%\%%S"

rem ---- build the SQLite script ----
set "SQLF=%WORK%\export.sql"
>"%SQLF%"  echo .bail on
>>"%SQLF%" echo .print [1/4] Finding the runs ...
>>"%SQLF%" echo CREATE TEMP TABLE runs AS SELECT SampleID, RunIDRecord FROM RunData WHERE SampleID IN (%INLIST%);
>>"%SQLF%" echo .print [2/4] Reading SystemMetrics ...
>>"%SQLF%" echo CREATE TEMP TABLE sm AS SELECT %SYS_COLS% FROM SystemMetrics WHERE RunIDRecord IN (SELECT RunIDRecord FROM runs);
>>"%SQLF%" echo CREATE TEMP TABLE t0s AS SELECT RunIDRecord, MIN(Timestamp) AS t0 FROM sm GROUP BY RunIDRecord;
>>"%SQLF%" echo .print [3/4] Reading ChannelData once for all runs (the slow step; nothing is written until it finishes) ...
>>"%SQLF%" echo CREATE TEMP TABLE ch AS SELECT %CH_COLS% FROM ChannelData c JOIN t0s ON c.RunIDRecord = t0s.RunIDRecord WHERE CAST(ROUND(c.TimeStamp - t0s.t0) AS INTEGER) %% %EVERY_SEC% = 0;
>>"%SQLF%" echo .print [4/4] Writing files ...
>>"%SQLF%" echo .headers on
>>"%SQLF%" echo .mode csv
for %%S in (%IDS%) do call :sql_for_sample %%S
>>"%SQLF%" echo .output stdout

rem ---- run it ----
echo Exporting %NIDS% sample(s) from "%DB%"
echo   working folder: "%WORK%"
echo   output folder:  "%OUTBASE%\<SampleID>"
set "IDX="
for /f "delims=" %%I in ('""%SQLITE%" -readonly "%DB%" ".indexes ChannelData""') do set "IDX=%%I"
if not defined IDX echo   NOTE: ChannelData has no index, so the whole ChannelData table is read - this can take several minutes.
echo [%time:~0,8%] started
"%SQLITE%" -readonly "%DB%" ".read '%SQLF%'"
if errorlevel 1 (
    echo sqlite3 reported an error - see above. Partial files are in "%WORK%".
    goto :end
)
echo [%time:~0,8%] export finished

rem ---- per sample: check, then copy to its output folder ----
set "NFAIL=0"
for %%S in (%IDS%) do call :finish_sample %%S
if "%NFAIL%"=="0" rmdir /s /q "%WORK%"
if not "%NFAIL%"=="0" echo %NFAIL% sample(s) not copied - their files are still in "%WORK%".
echo [%time:~0,8%] Done.
goto :end


rem =============================================================================================
:addid
rem add one sample ID (skips duplicates and samples already exported)
set "ID=%~1"
if "%ID%"=="" goto :eof
echo  %IDS% | findstr /i /c:" %ID% " >nul && goto :eof
if exist "%OUTBASE%\%ID%\ChannelData_%ID%.csv" (
    echo Skipping %ID%: already exported to "%OUTBASE%\%ID%"
    goto :eof
)
set "IDS=%IDS% %ID%"
set "INLIST=%INLIST%,'%ID%'"
set /a NIDS+=1
goto :eof

:sql_for_sample
set "S=%~1"
set "RUNQ=(SELECT RunIDRecord FROM runs WHERE SampleID = '%S%' LIMIT 1)"
>>"%SQLF%" echo .output '%WORK%\%S%\RunData_%S%.csv'
>>"%SQLF%" echo SELECT %RD_COLS% FROM RunData WHERE SampleID = '%S%';
>>"%SQLF%" echo .output '%WORK%\%S%\SystemMetrics_%S%.csv'
>>"%SQLF%" echo SELECT * FROM sm WHERE RunIDRecord = %RUNQ%;
>>"%SQLF%" echo .output '%WORK%\%S%\ChannelData_%S%.csv'
>>"%SQLF%" echo SELECT * FROM ch WHERE RunIDRecord = %RUNQ%;
goto :eof

:finish_sample
set "S=%~1"
echo %S%:
for %%T in (SystemMetrics ChannelData RunData) do call :count %%T
if "%CH_ROWS%"=="0" (
    echo   NOT FOUND or no data - check the Sample ID. Not copied.
    set /a NFAIL+=1
    goto :eof
)
robocopy "%WORK%\%S%" "%OUTBASE%\%S%" *.csv /R:3 /W:5 /NJH /NJS /NP /NDL /NFL >nul
if errorlevel 8 (
    echo   copy FAILED - files are still in "%WORK%\%S%"
    set /a NFAIL+=1
    goto :eof
)
echo   copied to "%OUTBASE%\%S%"
goto :eof

:count
set "ROWS=0"
set "BYTES=0"
if exist "%WORK%\%S%\%1_%S%.csv" (
    for /f %%N in ('type "%WORK%\%S%\%1_%S%.csv" ^| find /c /v ""') do set /a "ROWS=%%N-1"
    for %%F in ("%WORK%\%S%\%1_%S%.csv") do set "BYTES=%%~zF"
)
if %ROWS% LSS 0 set "ROWS=0"
if "%1"=="ChannelData" set "CH_ROWS=%ROWS%"
echo   %1: %ROWS% rows, %BYTES% bytes
goto :eof

:no_sqlite
echo sqlite3.exe not found. Put sqlite3.exe in the same folder as this .bat file:
echo   %HERE%
echo (download sqlite-tools-win-x64 from https://www.sqlite.org/download.html)

:end
if defined PROMPTED pause
endlocal

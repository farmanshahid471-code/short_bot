@echo off
rem Semi-automated Google Cloud + YouTube OAuth provisioner (Windows wrapper).
rem Usage:  provision.bat doctor | init | guide | verify | scaffold | connect | status
setlocal
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0provision.py" %*
) else (
    python "%~dp0provision.py" %*
)
endlocal

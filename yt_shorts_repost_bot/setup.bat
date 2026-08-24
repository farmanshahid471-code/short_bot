@echo off
setlocal EnableDelayedExpansion
title Shorts Repost Bot - Setup (Windows)
cd /d "%~dp0"

set "ROOT=%~dp0"

echo ==================================================
echo   Shorts Repost Bot - Automatic Setup - Windows
echo ==================================================
echo.
echo   This installs everything this bot needs, by itself:
echo     - FFmpeg, downloaded automatically if missing
echo     - Python packages, yt-dlp, YouTube API
echo     - Your settings file, .env
echo.
echo   First time only - takes about 2-10 minutes.
echo.

echo [1/4] Checking Python...

set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
where python >nul 2>&1
if not errorlevel 1 set "PY=python"

if defined PY goto :python_ok
echo.
echo   Python was NOT found on this computer.
echo   Please install it from:  https://www.python.org/downloads/
echo   IMPORTANT: during installation, tick the box that says
echo   "Add Python to PATH".
echo.
echo   Then close this window and double-click setup.bat again.
echo.
pause
exit /b 1

:python_ok
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo       Found: !PYVER!
echo.

echo [2/4] Checking FFmpeg...

where ffmpeg >nul 2>&1
if not errorlevel 1 goto :ffmpeg_ok

if exist "%ROOT%ffmpeg\bin\ffmpeg.exe" goto :ffmpeg_local

echo       FFmpeg not found. Trying the Windows Store installer, winget...
where winget >nul 2>&1
if errorlevel 1 goto :download_ffmpeg

winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto :download_ffmpeg

echo       FFmpeg installed via winget.
echo       It will be ready to use in new windows.
goto :ffmpeg_ok

:download_ffmpeg
echo.
echo       The automatic installer could not install FFmpeg.
echo       No problem - downloading a portable copy instead, about 100 MB...
echo.

set "FFZIP=%ROOT%ffmpeg.zip"
if exist "%FFZIP%" del /Q "%FFZIP%"

where curl >nul 2>&1
if not errorlevel 1 goto :use_curl

echo       Downloading with PowerShell...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.zip' -OutFile '%FFZIP%'"
if errorlevel 1 goto :ffmpeg_manual
if not exist "%FFZIP%" goto :ffmpeg_manual
goto :ffmpeg_extract

:use_curl
echo       Downloading with curl...
curl -L -sS -o "%FFZIP%" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.zip"
if errorlevel 1 goto :ffmpeg_manual
if not exist "%FFZIP%" goto :ffmpeg_manual

:ffmpeg_extract
echo       Download finished. Extracting...
cd /d "%ROOT%"

tar -xf "%FFZIP%"
if errorlevel 1 goto :use_expand
goto :after_extract

:use_expand
echo       Using PowerShell to extract...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%FFZIP%' -DestinationPath '%ROOT%' -Force"
if errorlevel 1 goto :ffmpeg_manual

:after_extract
for /d %%d in (ffmpeg-*) do xcopy /E /Y /I "%%d\bin" "ffmpeg\bin" >nul
for /d %%d in (ffmpeg-*) do rmdir /S /Q "%%d" >nul 2>&1
cd /d "%ROOT%"
del /Q "%FFZIP%" >nul 2>&1

if not exist "%ROOT%ffmpeg\bin\ffmpeg.exe" goto :ffmpeg_manual
echo       FFmpeg extracted to ffmpeg\bin
echo       The bot finds it automatically, no PATH changes needed.
goto :ffmpeg_ok

:ffmpeg_manual
echo.
echo   Automatic FFmpeg download failed too.
echo   Please do it manually:
echo     1. Go to:  https://www.gyan.dev/ffmpeg/builds/
echo     2. Download ffmpeg-release-full.zip
echo     3. Extract it, then COPY the bin folder from inside it
echo        into a folder named:  ffmpeg
echo        so that the file exists at:
echo        ffmpeg\bin\ffmpeg.exe
echo     4. Run setup.bat again.
echo.
pause
exit /b 1

:ffmpeg_local
echo       Using the bundled FFmpeg.
goto :ffmpeg_ok

:ffmpeg_ok
where ffmpeg >nul 2>&1
if not errorlevel 1 goto :ffmpeg_version
echo       FFmpeg is ready - bundled copy in ffmpeg\bin.
goto :ffmpeg_done

:ffmpeg_version
for /f "delims=" %%v in ('ffmpeg -version 2^>^&1 ^| findstr /b "ffmpeg version"') do echo       Found: %%v

:ffmpeg_done
echo.

echo [3/4] Setting up Python environment, first time downloads about 200 MB...

if exist ".venv\Scripts\python.exe" goto :venv_ok
%PY% -m venv .venv
if errorlevel 1 goto :venv_failed

:venv_ok
echo       Virtual environment ready.

echo       Installing packages, this can take a few minutes...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed
echo       All packages installed.
echo.

echo [4/4] Creating settings file...

if exist ".env" goto :env_exists
copy /Y .env.example .env >nul
echo       Created .env
goto :env_done

:env_exists
echo       .env already exists - leaving it unchanged.

:env_done
echo.

echo ==================================================
echo   DONE! Setup complete.
echo ==================================================
echo.
echo   Next steps:
echo     1. OPTIONAL: edit .env with Notepad - set TARGET_CHANNELS
echo        to the channels you want to grab Shorts from.
echo     2. Double-click  run_ui.bat  to open the control panel.
echo.
pause
exit /b 0

:venv_failed
echo.
echo   Failed to create the Python environment.
echo   Make sure Python is installed and try again.
echo.
pause
exit /b 1

:pip_failed
echo.
echo   Package installation failed. Check your internet connection
echo   and try again.
echo.
pause
exit /b 1

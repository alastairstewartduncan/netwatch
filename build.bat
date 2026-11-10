@echo off
REM ---------------------------------------------------------------------------
REM  Builds NetWatch:  dist\NetWatch-Setup-<version>.exe   (installer - give this to people)
REM                    dist\NetWatch-<version>-portable.zip (no-install copy)
REM                    dist\NetWatch\NetWatch.exe           (the app itself)
REM  Needs Python 3.12 on PATH. NSIS is installed automatically via winget if missing.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
title Building NetWatch

where python >nul 2>nul || (echo Python isn't installed or isn't on PATH. Get it from python.org and tick "Add python.exe to PATH". & goto :error)

echo Installing build dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || goto :error

where makensis >nul 2>nul
if errorlevel 1 if not exist "%ProgramFiles(x86)%\NSIS\makensis.exe" (
  echo.
  echo NSIS ^(the installer builder^) isn't installed - installing it with winget...
  winget install -e --id NSIS.NSIS --accept-package-agreements --accept-source-agreements
)

python tools\build.py || goto :error

echo.
echo ============================================================
echo  All done. Your installer is in the dist folder:
for %%f in (dist\NetWatch-Setup-*.exe) do echo    %%~ff
echo ============================================================
explorer dist
pause
exit /b 0

:error
echo.
echo Build failed - see the messages above.
pause
exit /b 1

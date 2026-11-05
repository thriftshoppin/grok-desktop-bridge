@echo off
setlocal EnableExtensions
title Grok Desktop Bridge - fresh install
cd /d "%~dp0"
set "PS1=%~dp0Install-GrokBridge.ps1"
set "GROK_PS1=%PS1%"
echo STEP: Install-GrokBridge.cmd
echo Script: %PS1%
if not exist "%PS1%" (
  echo ERROR: missing %PS1%
  echo FINAL EXIT CODE: 2
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p=$env:GROK_PS1; $errs=$null; $tok=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($p, [ref]$tok, [ref]$errs); if ($errs -and @($errs).Count -gt 0) { Write-Host 'PARSE FAILED'; foreach ($er in @($errs)) { Write-Host $er.ToString() }; exit 1 }; exit 0"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo PARSE CHECK FAILED
  echo FINAL EXIT CODE: %EC%
  pause
  exit /b %EC%
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -FromCmd %*
set "EC=%ERRORLEVEL%"
echo.
echo FINAL EXIT CODE: %EC%
pause
exit /b %EC%

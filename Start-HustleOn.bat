@echo off
REM Start-HustleOn - prefers the built exe, falls back to source.
if exist "%~dp0dist\hustle-on.exe" (
  start "" "%~dp0dist\hustle-on.exe"
) else (
  python "%~dp0hustleon_tray.py"
)

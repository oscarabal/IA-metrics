@echo off
rem Instala o reconfigura IA-metrics (elige Claude Code, OpenCode o ambos).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
if errorlevel 1 (
  echo.
  echo La instalacion no se completo. Revisa los mensajes anteriores.
)
pause

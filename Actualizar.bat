@echo off
rem Actualiza IA-metrics: codigo (git pull, si se puede), imagenes de Docker y arranque. Conserva el historial.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" -Update %*
if errorlevel 1 (
  echo.
  echo No se completo. Revisa los mensajes anteriores.
)
pause

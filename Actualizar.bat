@echo off
rem Actualiza IA-metrics: codigo (git pull, si se puede), imagenes y arranque. Conserva el historial.
rem Con Python 3 usa installer\install.py; sin el, un contenedor (ADR 0009). Todo en installer\run.bat.
cd /d "%~dp0"
set "IA_METRICS_MODE=update"
call "%~dp0installer\run.bat" %*
if errorlevel 1 (
  echo.
  echo No se completo. Revisa los mensajes anteriores.
)
pause

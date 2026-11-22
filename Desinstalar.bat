@echo off
rem Desinstala IA-metrics: contenedores, variables de telemetria de settings.json y acceso directo.
rem Con Python 3 usa installer\install.py; sin el, un contenedor (ADR 0009). Todo en installer\run.bat.
cd /d "%~dp0"
set "IA_METRICS_MODE=uninstall"
call "%~dp0installer\run.bat" %*
if errorlevel 1 (
  echo.
  echo No se completo. Revisa los mensajes anteriores.
)
pause

@echo off
rem Desinstala IA-metrics: contenedores, variables de telemetria de settings.json y acceso directo.
rem Pregunta antes de borrar el historial; Desinstalar.bat -RemoveData lo borra sin preguntar.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" -Uninstall %*
if errorlevel 1 (
  echo.
  echo No se completo. Revisa los mensajes anteriores.
)
pause

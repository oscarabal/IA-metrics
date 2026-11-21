@echo off
rem Instala o reconfigura IA-metrics (elige Claude Code, OpenCode o ambos).
cd /d "%~dp0"
set "PY=python"
where py >nul 2>&1 && set "PY=py -3"
%PY% --version >nul 2>&1 || ( echo No se encuentra Python 3. Instalalo desde https://www.python.org/downloads/ y vuelve a intentarlo. & pause & exit /b 1 )
%PY% "%~dp0installer\install.py" %*
if errorlevel 1 (
  echo.
  echo No se completo. Revisa los mensajes anteriores.
)
pause

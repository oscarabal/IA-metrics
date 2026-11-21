@echo off
rem Actualiza IA-metrics: codigo (git pull, si se puede), imagenes y arranque. Conserva el historial.
cd /d "%~dp0"
set "PY=python"
where py >nul 2>&1 && set "PY=py -3"
%PY% --version >nul 2>&1 || ( echo No se encuentra Python 3. Instalalo desde https://www.python.org/downloads/ y vuelve a intentarlo. & pause & exit /b 1 )
%PY% "%~dp0installer\install.py" --update %*
if errorlevel 1 (
  echo.
  echo No se completo. Revisa los mensajes anteriores.
)
pause

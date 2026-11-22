@echo off
rem Lanzador comun de Instalar.bat, Actualizar.bat y Desinstalar.bat (Windows).
rem El modo llega en IA_METRICS_MODE (install, update, uninstall) y %* son las opciones de install.py.
rem Con Python 3 en el equipo llama a installer\install.py. Sin el (ADR 0009) ejecuta install.py en un contenedor
rem (la misma imagen que los colectores) y hace aqui lo que necesita Docker o el escritorio: arrancar la pila,
rem actualizar, quitar los contenedores y el acceso directo. IA_METRICS_INSTALLER=docker fuerza el contenedor.
setlocal EnableExtensions
cd /d "%~dp0.."
set "MODE=%IA_METRICS_MODE%"
if not defined MODE set "MODE=install"
rem Misma imagen que x-collector en docker-compose.yml (tests/test_config.py lo comprueba)
set "PY_IMAGE=python:3.13-alpine"
set "ACTIONS=installer\.host-actions"
set "FORCE=0"
echo %* | find /i "--force" >nul && set "FORCE=1"

rem ---------------------------------------------------------------- con Python
if /i "%IA_METRICS_INSTALLER%"=="docker" goto docker
set "PY="
where py >nul 2>&1 && py -3 --version >nul 2>&1 && set "PY=py -3"
rem El alias de la Microsoft Store tambien se llama python, pero --version falla
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY goto docker
if /i "%MODE%"=="update" goto py_update
if /i "%MODE%"=="uninstall" goto py_uninstall
%PY% installer\install.py %*
exit /b %errorlevel%
:py_update
%PY% installer\install.py --update %*
exit /b %errorlevel%
:py_uninstall
%PY% installer\install.py --uninstall %*
exit /b %errorlevel%

rem ---------------------------------------------------------------- sin Python: Docker
:docker
where docker >nul 2>&1 || goto no_docker
call :ensure_docker
if errorlevel 1 exit /b 1
if /i "%MODE%"=="install" goto docker_install
if /i "%MODE%"=="update" goto docker_update
if /i "%MODE%"=="uninstall" goto docker_uninstall
echo Modo desconocido: %MODE%
exit /b 2

:no_docker
echo No se encuentra ni Python 3 ni Docker. Instala Docker Desktop, Rancher Desktop o Podman con docker compose
echo y vuelve a intentarlo.
exit /b 1

:docker_install
call :run_in_container %*
if errorlevel 1 exit /b 1
if defined HA_OPENCODE_DIRS (
  if not exist "%USERPROFILE%\.config\opencode\commands" mkdir "%USERPROFILE%\.config\opencode\commands"
  if not exist "%USERPROFILE%\.cache\opencode" mkdir "%USERPROFILE%\.cache\opencode"
)
if defined HA_SHORTCUT call :shortcut
if not defined HA_START exit /b 0
rem quita los servicios del perfil que ya no se usa; Iniciar-metricas.bat levanta los elegidos y avisa de precios
docker compose --profile claude --profile opencode stop >nul 2>&1
call "%CD%\Iniciar-metricas.bat"
exit /b %errorlevel%

:docker_update
echo == Actualizar IA-metrics ==
call :git_update
echo Descargando las imagenes de Docker...
docker compose pull
if errorlevel 1 ( echo Fallo: docker compose pull & exit /b 1 )
docker compose up -d --remove-orphans
if errorlevel 1 ( echo Fallo: docker compose up & exit /b 1 )
echo Esperando a que los servicios esten listos...
docker compose up -d --wait --wait-timeout 180 >nul 2>&1 || echo AVISO: algun servicio no esta sano todavia. Revisalo con: docker compose ps
echo IA-metrics actualizado. El historial se conserva.
exit /b 0

:docker_uninstall
call :run_in_container --uninstall %*
if errorlevel 1 exit /b 1
if not defined HA_DOWN goto uninstall_shortcut
if defined HA_REMOVE_DATA (
  docker compose --profile claude --profile opencode down --remove-orphans -v || exit /b 1
  echo Contenedores y volumenes eliminados.
) else (
  docker compose --profile claude --profile opencode down --remove-orphans || exit /b 1
  echo Contenedores eliminados; el historial sigue en los volumenes ia-metrics_* y se recupera al reinstalar.
)
:uninstall_shortcut
if defined HA_REMOVE_SHORTCUT if exist "%USERPROFILE%\Desktop\IA-metrics.lnk" del /q "%USERPROFILE%\Desktop\IA-metrics.lnk" && echo Acceso directo eliminado.
if defined HA_DOWN echo.
if defined HA_DOWN echo IA-metrics desinstalado. Para quitarlo del todo, borra la carpeta del proyecto.
exit /b 0

rem ---------------------------------------------------------------- subrutinas
:ensure_docker
docker info >nul 2>&1 && exit /b 0
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
  echo Docker no esta en marcha. Iniciando Docker Desktop...
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
)
set /a n=0
:ensure_wait
timeout /t 5 /nobreak >nul
docker info >nul 2>&1 && exit /b 0
set /a n+=1
if %n% GEQ 36 goto ensure_fail
echo Esperando a Docker... (%n%/36)
goto ensure_wait
:ensure_fail
echo Docker no arranco a tiempo. Abrelo a mano y vuelve a intentarlo.
exit /b 1

rem install.py en el contenedor: decide, edita .env y settings.json, y deja en %ACTIONS% lo que hay que hacer aqui
:run_in_container
set "CLAUDE_HOST=%USERPROFILE%\.claude"
if defined CLAUDE_DIR set "CLAUDE_HOST=%CLAUDE_DIR%"
if not exist "%CLAUDE_HOST%" mkdir "%CLAUDE_HOST%"
set "OCDB=0"
if exist "%USERPROFILE%\.local\share\opencode\opencode.db" set "OCDB=1"
set "WINTZ="
for /f "delims=" %%t in ('tzutil /g 2^>nul') do set "WINTZ=%%t"
if exist "%ACTIONS%" del /q "%ACTIONS%"
echo Python 3 no esta instalado: el instalador se ejecuta en un contenedor (%PY_IMAGE%).
rem UTF-8 en la consola para los acentos que escribe install.py
chcp 65001 >nul
docker run --rm -it -v "%CD%:/repo" -v "%CLAUDE_HOST%:/host/claude" -w /repo -e CLAUDE_DIR=/host/claude -e HOME=/tmp -e IA_METRICS_HOST_ACTIONS=/repo/installer/.host-actions -e "HOST_CLAUDE_DIR=%CLAUDE_HOST%" -e "HOST_HOME=%USERPROFILE%" -e HOST_OPENCODE_DB=%OCDB% -e "HOST_TZ_WINDOWS=%WINTZ%" -e PYTHONIOENCODING=utf-8 %PY_IMAGE% python installer/install.py %*
set "RC=%errorlevel%"
set "HA_START=" & set "HA_SHORTCUT=" & set "HA_OPENCODE_DIRS=" & set "HA_DOWN=" & set "HA_REMOVE_DATA=" & set "HA_REMOVE_SHORTCUT="
if exist "%ACTIONS%" for /f "usebackq tokens=1,2 delims==" %%a in ("%ACTIONS%") do set "HA_%%a=%%b"
if exist "%ACTIONS%" del /q "%ACTIONS%"
exit /b %RC%

:shortcut
set "LNK=%USERPROFILE%\Desktop\IA-metrics.lnk"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');$s.TargetPath='%CD%\Iniciar-metricas.bat';$s.WorkingDirectory='%CD%';$s.IconLocation='%CD%\installer\metricas.ico';$s.Save()" >nul 2>&1
if exist "%LNK%" echo Acceso directo creado en el escritorio: %LNK%
exit /b 0

:git_update
if not exist ".git" exit /b 0
where git >nul 2>&1 || exit /b 0
set "REMOTE="
for /f "delims=" %%r in ('git remote 2^>nul') do set "REMOTE=%%r"
if not defined REMOTE ( echo El repositorio no tiene remoto: no se descarga codigo nuevo. & exit /b 0 )
set "DIRTY="
for /f "delims=" %%d in ('git status --porcelain 2^>nul') do set "DIRTY=1"
if defined DIRTY ( echo Hay cambios locales sin commit: no se descarga codigo nuevo, para no mezclarlos. & exit /b 0 )
if "%FORCE%"=="1" goto git_pull
choice /c SN /m "Descargo la ultima version del codigo con git pull --ff-only"
if errorlevel 2 exit /b 0
:git_pull
git pull --ff-only || echo git pull no pudo avanzar: se sigue con el codigo actual.
exit /b 0

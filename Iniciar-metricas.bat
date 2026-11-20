@echo off
rem Arranca la pila de IA-metrics con las herramientas elegidas en la instalacion y abre Grafana.
cd /d "%~dp0"

if not exist ".env" (
  echo Falta el fichero .env. Ejecuta primero Instalar.bat.
  pause
  exit /b 1
)

docker info >nul 2>&1 && goto up

echo Docker no esta en marcha. Iniciando Docker Desktop...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
set /a n=0

:wait
timeout /t 5 /nobreak >nul
docker info >nul 2>&1 && goto up
set /a n+=1
if %n% GEQ 36 goto fail
echo Esperando a Docker... (%n%/36)
goto wait

:up
echo Levantando IA-metrics...
docker compose up -d
if errorlevel 1 goto fail
echo Esperando a que los servicios esten listos...
docker compose up -d --wait --wait-timeout 180 >nul 2>&1 || echo AVISO: algun servicio no esta sano todavia. Revisalo con: docker compose ps
start "" http://localhost:3000
echo.
echo Listo. Grafana: http://localhost:3000
call :precios claude-collector 9100 "collectors\claude\prices.json" "docker compose restart claude-collector"
call :precios opencode-collector 9101 "la configuracion de OpenCode (provider.ID.models.ID.cost)" "reinicia OpenCode (solo cambia el coste de los mensajes nuevos)"
timeout /t 5 >nul
exit /b 0

rem Avisa si alguno de tus modelos no tiene precio (%1 colector, %2 puerto, %3 donde se arregla, %4 que hacer despues).
rem Solo si ese colector esta en marcha; espera como mucho 2 minutos a que haya leido tus datos.
:precios
docker compose ps --services --status running 2>nul | findstr /x "%~1" >nul || exit /b 0
set "PRECIOS=%TEMP%\ia-metrics-precios-%~2.txt"
set /a p=0
:precios_espera
curl.exe -s http://localhost:%~2/prices/missing > "%PRECIOS%" 2>nul
findstr /b "OK" "%PRECIOS%" >nul && exit /b 0
findstr /b "SIN" "%PRECIOS%" >nul && goto precios_aviso
set /a p+=1
if %p% GEQ 24 exit /b 0
timeout /t 5 /nobreak >nul
goto precios_espera
:precios_aviso
echo.
echo AVISO (%~1): modelos sin precio; su coste no cuenta en el dashboard:
more +1 "%PRECIOS%"
echo Anade su precio en %~3 y despues: %~4
echo Detalle: http://localhost:%~2/prices
pause
exit /b 0

:fail
echo.
echo ERROR: no se pudo levantar la pila. Revisa que Docker este instalado y arrancado.
pause
exit /b 1

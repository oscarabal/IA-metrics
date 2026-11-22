# ADR 0009: Python en el equipo deja de ser requisito: el instalador corre en un contenedor si falta

- **Estado:** aceptada
- **Fecha:** 2026-11-22
- **Modifica:** [ADR 0008](0008-instalador-unico-en-python-multiplataforma.md) (su consecuencia «Nuevo requisito: Python 3»).

## Contexto

ADR 0008 sustituyó `install.ps1` por un único `installer/install.py` y, a cambio, añadió **Python 3** como
requisito del equipo, además de Docker. En macOS y Linux suele estar, pero Windows no lo trae: el usuario tiene que
instalarlo, y el alias `python` de la Microsoft Store confunde a quien no lo conoce. En macOS sin Command Line Tools,
`/usr/bin/python3` es solo un aviso que abre un diálogo de instalación. La restricción original (ADR 0001) era
«Docker como único requisito».

Docker ya es obligatorio y la imagen de los colectores (`python:3.13-alpine`) trae Python. Pero `install.py` no
puede ejecutarse entero en un contenedor:

- `docker compose` resuelve las rutas de los montajes (`./collectors`, `${USERPROFILE}/.claude/projects`) donde se
  ejecuta. Dentro de un contenedor serían rutas del contenedor y el demonio no las encontraría.
- Arrancar Docker Desktop, crear el acceso directo `.lnk` o `.desktop`, leer la zona horaria (`tzutil`) y `git pull`
  son cosas del equipo.

Opciones consideradas:

1. **Todo en el contenedor con el socket de Docker montado.** Falla por las rutas de compose. Además exige una
   imagen con Docker CLI y Python, y da al instalador acceso total al demonio.
2. **Empaquetar `install.py` como `.exe` (PyInstaller) en el CI.** No hay que tener Python, pero hay que firmar y
   publicar un binario por sistema, y los antivirus de empresa suelen marcarlos.
3. **Reescribir el instalador en `.bat` + `.sh`.** Es justo lo que ADR 0008 quiso evitar: dos instaladores.
4. **Dividir el trabajo.** `install.py` corre en el contenedor y hace lo que sabe hacer sin Docker: preguntar,
   decidir, editar `.env` y `settings.json`. Un lanzador fino en el equipo hace el resto.

## Decisión

Opción 4, y **solo cuando no hay Python**. Con Python 3 en el equipo nada cambia.

- `Instalar.bat`, `Actualizar.bat` y `Desinstalar.bat` llaman a `installer/run.bat`. Los `.sh` llaman a
  `installer/run.sh`. El lanzador busca un Python 3 que funcione: descarta el alias de la Store y el aviso de
  macOS. Si lo encuentra, llama a `install.py` como antes.
- **Sin Python**, el lanzador ejecuta `install.py` en `python:3.13-alpine` (la misma imagen que los colectores,
  comprobado por test). Monta el repositorio en `/repo` y `~/.claude` en `/host/claude`, y nada más. Al contenedor
  le pasa lo que no puede ver por sí mismo: la zona horaria (`HOST_TZ` o `HOST_TZ_WINDOWS`), si existe
  `opencode.db` (`HOST_OPENCODE_DB`) y las rutas del equipo para los mensajes (`HOST_CLAUDE_DIR`, `HOST_HOME`).
  En Linux usa `--user` para que los ficheros no queden como root.
- **Modo delegado de `install.py`** (`IA_METRICS_HOST_ACTIONS`). Hace lo mismo que con Python, pero cada paso que
  necesita Docker o el escritorio lo apunta en `installer/.host-actions` (`START`, `SHORTCUT`, `OPENCODE_DIRS`,
  `DOWN`, `REMOVE_DATA`, `REMOVE_SHORTCUT`). El lanzador los ejecuta después y borra el fichero. Las decisiones
  siguen en un solo sitio, `install.py`.
- **Actualizar y arrancar** no usan el contenedor: son `git pull` y `docker compose`. Los lanzadores los hacen
  directamente (en Windows, arrancar ya era `Iniciar-metricas.bat`, sin Python).
- **Migrar las pilas antiguas** (`claude-metrics`, `opencode-metrics`) no se hace sin Python: necesita Docker y solo
  le sirve a quien venía de esas pilas. El instalador lo avisa.
- `IA_METRICS_INSTALLER=docker` fuerza el contenedor aunque haya Python, para probarlo.

## Consecuencias

- Vuelve a bastar con **Docker** para instalar, actualizar, desinstalar y arrancar en Windows, macOS y Linux.
- El instalador sigue siendo un único `install.py`. Los lanzadores ganan lógica (arrancar Docker, `git pull`,
  `compose down`, acceso directo), duplicada en `run.bat` y `run.sh`. `tests/test_config.py` comprueba que cada
  acción que `install.py` puede delegar la atienden los dos lanzadores, que usan la imagen del compose, sus finales
  de línea y la sintaxis de `run.sh`. `tests/test_installer.py` prueba el modo delegado de principio a fin sin
  Docker: falla si `install.py` intenta lanzar cualquier proceso.
- `run.bat` no se puede probar en el CI de Linux: queda como riesgo y se prueba a mano en Windows
  (`set IA_METRICS_INSTALLER=docker` y `Instalar.bat`).
- La consola de Windows pasa a UTF-8 (`chcp 65001`) mientras corre el contenedor, para los acentos.
- El lanzador `.desktop` de Linux apunta ahora a `iniciar-metricas.sh`, que funciona con Python y sin él.
- De paso se corrigieron dos fallos del instalador: `--tools claude` partía el valor en letras
  (`",".join(args.tools)` sobre una cadena) y `read_env_file()` fijaba la ruta de `.env` al importarse.

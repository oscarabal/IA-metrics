# ADR 0008: Instalador único en Python, multiplataforma

- **Estado:** aceptada; el requisito de Python 3 lo retira [ADR 0009](0009-instalador-sin-python-en-el-equipo.md)
- **Fecha:** 2026-11-21
- **Sustituye a:** el instalador `installer/install.ps1` (PowerShell 5.1, solo Windows).

## Contexto

La pila ya corría en cualquier sistema con Docker: el `docker-compose.yml` cae de `${USERPROFILE}` (Windows) a
`${HOME}` (macOS, Linux) y los colectores son Python puro. Lo único atado a Windows era la capa de instalación:
`install.ps1` (PowerShell 5.1, acceso directo `.lnk`, mapa de zonas de Windows, arrancar Docker Desktop por
ruta fija) y los `.bat`. El objetivo pasó a ser soportar también macOS y Linux.

Opciones consideradas para el instalador multiplataforma:

- **`npx` / paquete Node.** Añade Node.js como requisito (no garantizado en Windows), exige publicar y mantener
  un paquete npm, y no evita tener el repo en disco (el compose monta `./collectors`, `./config`, `./grafana`);
  además choca con `--update` por `git pull`. Descartado.
- **`install.ps1` (Windows) + `install.sh` (Unix).** No añade requisitos, pero son dos instaladores que mantener
  en paralelo, y editar `settings.json` (JSON) en bash es incómodo.
- **Un solo `install.py` en Python 3.** Una sola base de código para los tres sistemas, coherente con el resto
  del proyecto (todo es Python de la librería estándar), y fácil de probar sin `pwsh`.

## Decisión

Un único `installer/install.py` (Python 3, solo librería estándar) sustituye a `install.ps1`. Los lanzadores
son finos: `Instalar.bat` / `Actualizar.bat` / `Desinstalar.bat` (Windows, CRLF) y `instalar.sh` /
`actualizar.sh` / `desinstalar.sh` / `iniciar-metricas.sh` (Unix, LF) solo llaman a `install.py` con el modo
correspondiente (`--update`, `--uninstall`, `--start`). `Iniciar-metricas.bat` se mantiene (arranca Docker
Desktop en Windows y hace su aviso de precios); el aviso de precios se portó a `install.py` para los tres SO.

Detalles por sistema, todos dentro de `install.py`:

- **Arrancar Docker:** Windows lanza `Docker Desktop.exe`; macOS, `open -a Docker`; Linux avisa y espera a que
  el usuario arranque el servicio.
- **Zona horaria:** en Unix se lee de `/etc/localtime` o `/etc/timezone`; en Windows, de `tzutil /g` con un mapa
  Windows→IANA de respaldo.
- **Acceso directo:** `.lnk` en el escritorio en Windows (vía PowerShell), `.desktop` en Linux, nada en macOS.
- **settings.json:** mismo `~/.claude/settings.json` en los tres; se escribe en UTF-8 sin BOM, con copia previa.

## Consecuencias

- IA-metrics se instala en Windows, macOS y Linux con el mismo instalador.
- **Nuevo requisito: Python 3** en el equipo (ya está en macOS y Linux; en Windows hay que tenerlo; los `.bat`
  avisan si falta). Docker sigue siendo el otro requisito.
- Menos código y más fácil de probar: las funciones puras del instalador se prueban en `tests/test_installer.py`
  sin `pwsh` ni Docker, así que corren en el CI de Linux (antes el test del instalador se saltaba sin `pwsh`).
- Se retiran `installer/install.ps1` y `tests/installer_uninstall.ps1`.

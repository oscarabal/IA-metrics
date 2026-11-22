#!/usr/bin/env bash
# Lanzador común de instalar.sh, actualizar.sh, desinstalar.sh e iniciar-metricas.sh (macOS y Linux).
#   installer/run.sh install|update|uninstall|start [opciones de install.py]
# Con Python 3 en el equipo llama a installer/install.py. Sin él (ADR 0009) ejecuta install.py en un contenedor
# (la misma imagen que los colectores) y hace aquí lo que necesita Docker o el escritorio: arrancar la pila,
# actualizar, quitar los contenedores y el lanzador. IA_METRICS_INSTALLER=docker fuerza el contenedor.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)
MODE=${1:-install}
[ $# -gt 0 ] && shift
# Misma imagen que x-collector en docker-compose.yml (tests/test_config.py lo comprueba)
PY_IMAGE="python:3.13-alpine"
ACTIONS="installer/.host-actions"

say() { printf '%s\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- ¿hay Python 3 de verdad?
find_python() {
  [ "${IA_METRICS_INSTALLER:-}" = "docker" ] && return 1
  for c in python3 python; do
    command -v "$c" >/dev/null 2>&1 || continue
    # macOS sin Command Line Tools: /usr/bin/python3 es un aviso que abre un diálogo de instalación
    if [ "$(uname -s)" = "Darwin" ] && [ "$(command -v "$c")" = "/usr/bin/python3" ] \
       && ! xcode-select -p >/dev/null 2>&1; then
      continue
    fi
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
      PY=$c
      return 0
    fi
  done
  return 1
}

if find_python; then
  case $MODE in
    install)   exec "$PY" installer/install.py "$@" ;;
    update)    exec "$PY" installer/install.py --update "$@" ;;
    uninstall) exec "$PY" installer/install.py --uninstall "$@" ;;
    start)     exec "$PY" installer/install.py --start "$@" ;;
    *)         say "Modo desconocido: $MODE"; exit 2 ;;
  esac
fi

# ---------------------------------------------------------------- sin Python: Docker
has_arg() { local a; for a in "${@:2}"; do [ "$a" = "$1" ] && return 0; done; return 1; }
FORCE=0; has_arg --force "$@" && FORCE=1

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    say "No se encuentra ni Python 3 ni Docker. Instala Docker (Docker Desktop, Rancher Desktop o Podman con"
    say "docker compose) y vuelve a intentarlo."
    exit 1
  fi
  docker info >/dev/null 2>&1 && return 0
  if [ "$(uname -s)" = "Darwin" ]; then
    say "Docker no está en marcha. Iniciando Docker..."
    open -a Docker 2>/dev/null
  else
    warn "Docker no está en marcha. Arráncalo (por ejemplo: sudo systemctl start docker) y espero..."
  fi
  for n in $(seq 1 36); do
    sleep 5
    docker info >/dev/null 2>&1 && return 0
    say "Esperando a Docker... ($n/36)"
  done
  say "Docker no arrancó a tiempo. Ábrelo a mano y vuelve a intentarlo."
  exit 1
}

host_tz() {
  local tz
  tz=$(readlink /etc/localtime 2>/dev/null | sed -n 's|.*zoneinfo/||p')
  [ -z "$tz" ] && [ -r /etc/timezone ] && tz=$(head -n1 /etc/timezone)
  printf '%s' "${tz:-${TZ:-}}"
}

# install.py en el contenedor: decide, edita .env y settings.json, y deja en $ACTIONS lo que hay que hacer aquí
run_in_container() {
  local claude_host="${CLAUDE_DIR:-$HOME/.claude}" oc=0 tty=-i
  mkdir -p "$claude_host"   # que no lo cree Docker como root
  [ -e "$HOME/.local/share/opencode/opencode.db" ] && oc=1
  [ -t 0 ] && [ -t 1 ] && tty=-it
  rm -f "$ACTIONS"
  say "Python 3 no está instalado: el instalador se ejecuta en un contenedor ($PY_IMAGE)."
  docker run --rm $tty \
    --user "$(id -u):$(id -g)" \
    -v "$ROOT:/repo" -v "$claude_host:/host/claude" -w /repo \
    -e CLAUDE_DIR=/host/claude -e HOME=/tmp \
    -e IA_METRICS_HOST_ACTIONS=/repo/$ACTIONS \
    -e HOST_CLAUDE_DIR="$claude_host" -e HOST_HOME="$HOME" \
    -e HOST_OPENCODE_DB=$oc -e HOST_TZ="$(host_tz)" \
    -e NO_COLOR="${NO_COLOR:-}" \
    "$PY_IMAGE" python installer/install.py "$@"
  local rc=$?
  HA=""
  [ -f "$ACTIONS" ] && HA=$(cat "$ACTIONS") && rm -f "$ACTIONS"
  return $rc
}
action() { printf '%s\n' "$HA" | grep -qx "$1=1"; }

open_url() {
  [ -n "${NO_BROWSER:-}" ] && return 0
  if command -v open >/dev/null 2>&1 && [ "$(uname -s)" = "Darwin" ]; then open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 &
  fi
}

# Aviso de modelos sin precio, como Iniciar-metricas.bat
check_prices() {
  command -v curl >/dev/null 2>&1 || return 0
  local svc port status i
  for svc in claude-collector:9100 opencode-collector:9101; do
    port=${svc#*:}; svc=${svc%%:*}
    docker compose ps --services --status running 2>/dev/null | grep -qx "$svc" || continue
    status=""
    for i in 1 2 3 4 5 6; do
      status=$(curl -s "http://localhost:$port/prices/missing" 2>/dev/null)
      case $status in OK*|SIN*) break ;; esac
      sleep 5
    done
    case $status in SIN*)
      say ""
      warn "AVISO ($svc): modelos sin precio; su coste no cuenta en el dashboard:"
      printf '%s\n' "$status" | tail -n +2
      say "Detalle: http://localhost:$port/prices" ;;
    esac
  done
}

start_stack() {
  [ -f .env ] || { say "Falta el fichero .env. Ejecuta primero ./instalar.sh."; exit 1; }
  ensure_docker
  say "Levantando IA-metrics..."
  docker compose up -d --remove-orphans || { say "ERROR: no se pudo levantar la pila."; exit 1; }
  say "Esperando a que los servicios estén listos..."
  docker compose up -d --wait --wait-timeout 180 >/dev/null 2>&1 \
    || warn "Algún servicio no está sano todavía. Revísalo con: docker compose ps"
  say ""
  say "Listo."
  say "  Grafana:            http://localhost:3000  (usuario admin)"
  docker compose ps --services 2>/dev/null | grep -qx claude-collector && say "  Sesiones Claude:    http://localhost:9100/sessions"
  docker compose ps --services 2>/dev/null | grep -qx opencode-collector && say "  Sesiones OpenCode:  http://localhost:9101/sessions"
  check_prices
  open_url http://localhost:3000
}

git_update() {
  [ -d .git ] && command -v git >/dev/null 2>&1 || return 0
  if [ -z "$(git remote)" ]; then
    say "El repositorio no tiene remoto: no se descarga código nuevo."
  elif [ -n "$(git status --porcelain)" ]; then
    warn "Hay cambios locales sin commit: no se descarga código nuevo (git pull) para no mezclarlos."
  else
    if [ $FORCE -eq 0 ]; then
      printf '¿Descargo la última versión del código? (git pull --ff-only) [S/n] '
      read -r a || a=""
      case $a in n|N|no|NO) return 0 ;; esac
    fi
    git pull --ff-only || warn "git pull no pudo avanzar (ramas divergentes o sin red): se sigue con el código actual."
  fi
}

case $MODE in
  install)
    ensure_docker
    run_in_container "$@" || exit 1
    if action OPENCODE_DIRS; then mkdir -p "$HOME/.config/opencode/commands" "$HOME/.cache/opencode"; fi
    if action SHORTCUT && [ "$(uname -s)" != "Darwin" ]; then
      mkdir -p "$HOME/.local/share/applications"
      printf '[Desktop Entry]\nType=Application\nName=IA-metrics\nExec=%s\nTerminal=true\nCategories=Development;\n' \
        "$ROOT/iniciar-metricas.sh" > "$HOME/.local/share/applications/ia-metrics.desktop"
      say "Lanzador creado: $HOME/.local/share/applications/ia-metrics.desktop"
    fi
    if action START; then
      # quita los servicios del perfil que ya no se usa y levanta los elegidos
      docker compose --profile claude --profile opencode stop >/dev/null 2>&1
      start_stack
    fi
    ;;
  update)
    say "== Actualizar IA-metrics =="
    ensure_docker
    git_update
    say "Descargando las imágenes de Docker..."
    docker compose pull || { say "Falló: docker compose pull"; exit 1; }
    docker compose up -d --remove-orphans || { say "Falló: docker compose up"; exit 1; }
    say "Esperando a que los servicios estén listos..."
    docker compose up -d --wait --wait-timeout 180 >/dev/null 2>&1 \
      || warn "Algún servicio no está sano todavía. Revísalo con: docker compose ps"
    say "IA-metrics actualizado. El historial se conserva."
    ;;
  uninstall)
    ensure_docker
    run_in_container --uninstall "$@" || exit 1
    if action DOWN; then
      if action REMOVE_DATA; then
        docker compose --profile claude --profile opencode down --remove-orphans -v || exit 1
        say "Contenedores y volúmenes eliminados."
      else
        docker compose --profile claude --profile opencode down --remove-orphans || exit 1
        say "Contenedores eliminados; el historial sigue en los volúmenes ia-metrics_* (se recupera al reinstalar)."
      fi
    fi
    if action REMOVE_SHORTCUT && [ -f "$HOME/.local/share/applications/ia-metrics.desktop" ]; then
      rm -f "$HOME/.local/share/applications/ia-metrics.desktop" && say "Lanzador eliminado."
    fi
    action DOWN && { say ""; say "IA-metrics desinstalado. Para quitarlo del todo, borra la carpeta del proyecto."; }
    ;;
  start)
    start_stack
    ;;
  *)
    say "Modo desconocido: $MODE"; exit 2 ;;
esac

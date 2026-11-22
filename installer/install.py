#!/usr/bin/env python3
"""Instalador multiplataforma de IA-metrics (Windows, macOS, Linux).

Elige qué medir (Claude Code, OpenCode o ambos), genera .env, activa la telemetría de Claude Code en
~/.claude/settings.json, migra las pilas antiguas y arranca la pila. Con --update la actualiza y con
--uninstall la desinstala. Solo necesita Python 3 y Docker con `docker compose`.

    python3 installer/install.py                     # interactivo
    python3 installer/install.py --tools claude,opencode
    python3 installer/install.py --update
    python3 installer/install.py --uninstall [--remove-data] [--force]
    python3 installer/install.py --start             # solo arrancar y abrir Grafana

Las funciones puras (env, settings.json, selección, zona horaria) no tocan Docker: los tests las usan.

Sin Python en el equipo, los lanzadores (installer/run.bat, installer/run.sh) ejecutan este fichero dentro de un
contenedor: es el modo delegado (ADR 0009). Ver HOST_ACTIONS.
"""
import argparse
import datetime
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT, ".env")
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")
HOME = os.path.expanduser("~")
CLAUDE_DIR = os.environ.get("CLAUDE_DIR") or os.path.join(HOME, ".claude")
OPENCODE_DB = os.path.join(HOME, ".local", "share", "opencode", "opencode.db")
IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"

# Modo delegado (ADR 0009): sin Python en el equipo, el lanzador ejecuta este fichero en python:3.13-alpine con el
# repositorio en /repo y ~/.claude montado en CLAUDE_DIR. Ahí se decide todo y se editan .env y settings.json, pero
# no hay Docker ni escritorio: cada paso que los necesita se apunta como CLAVE=1 en este fichero y lo hace el
# lanzador al terminar (START, SHORTCUT, OPENCODE_DIRS, DOWN, REMOVE_DATA, REMOVE_SHORTCUT).
HOST_ACTIONS = os.environ.get("IA_METRICS_HOST_ACTIONS", "")
DELEGATED = bool(HOST_ACTIONS)
# Rutas del equipo, para que los mensajes no muestren las del contenedor (/host/claude, /root)
_HOST_PATHS = ((CLAUDE_DIR, os.environ.get("HOST_CLAUDE_DIR", "")), (HOME, os.environ.get("HOST_HOME", "")))

# Variables de telemetría que el instalador pone en settings.json (y que Desinstalar quita si siguen con este valor)
TELEMETRY_ENV = {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
    "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": "cumulative",
}
RETENTION_DAYS = 90
PASSWORD_CHARS = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MIGRATE_VOLUMES = ("prometheus-data", "loki-data", "coach-data")  # solo el historial de Claude Code
# Windows no usa nombres IANA; mapa de respaldo cuando no se puede convertir automáticamente
WINDOWS_TO_IANA = {
    "Romance Standard Time": "Europe/Madrid", "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest", "Central European Standard Time": "Europe/Warsaw",
    "GMT Standard Time": "Europe/London", "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Canary Standard Time": "Atlantic/Canary", "E. Europe Standard Time": "Europe/Chisinau",
    "FLE Standard Time": "Europe/Kiev", "GTB Standard Time": "Europe/Bucharest",
    "Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver", "Pacific Standard Time": "America/Los_Angeles",
    "Central Standard Time (Mexico)": "America/Mexico_City", "SA Pacific Standard Time": "America/Bogota",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires", "Pacific SA Standard Time": "America/Santiago",
    "E. South America Standard Time": "America/Sao_Paulo", "UTC": "UTC",
}

_COLOR = {"gray": "", "cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m", "red": "\033[31m"}
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def say(text, color="gray"):
    if _USE_COLOR and _COLOR.get(color):
        print("%s%s\033[0m" % (_COLOR[color], text))
    else:
        print(text)


def ask_yes_no(question, default=True):
    suffix = "[S/n]" if default else "[s/N]"
    try:
        a = input("%s %s " % (question, suffix)).strip().lower()
    except EOFError:
        return default
    if not a:
        return default
    return a in ("s", "si", "sí", "y", "yes")


def shown(path):
    """La ruta tal como la ve el usuario en su equipo (en modo delegado, la del contenedor traducida)."""
    for inner, outer in _HOST_PATHS:
        if outer and (path == inner or path.startswith(inner.rstrip("/") + "/")):
            rest = path[len(inner):]
            return outer.rstrip("/\\") + (rest.replace("/", "\\") if "\\" in outer else rest)
    return path


def host_action(key, value="1"):
    """Modo delegado: apunta un paso que hará el lanzador en el equipo."""
    with open(HOST_ACTIONS, "a", encoding="utf-8", newline="\n") as f:
        f.write("%s=%s\n" % (key, value))


def read_host_actions(path):
    """{CLAVE: valor} del fichero de acciones (lo usan los tests; los lanzadores lo leen por su cuenta)."""
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                k, sep, v = line.strip().partition("=")
                if sep:
                    out[k] = v
    return out


def opencode_present():
    """Si existe opencode.db. En modo delegado lo dice el lanzador (HOST_OPENCODE_DB=1/0): no se monta esa carpeta."""
    flag = os.environ.get("HOST_OPENCODE_DB", "")
    if flag in ("0", "1"):
        return flag == "1"
    return os.path.exists(OPENCODE_DB)


# ---------------------------------------------------------------- .env (preserva comentarios)
def read_env_file(path=None):
    path = path or ENV_FILE   # en tiempo de llamada: así los tests pueden apuntar a otro .env
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line)
                if m:
                    out[m.group(1)] = m.group(2).rstrip("\n")
    return out


def set_env_value(lines, key, value):
    """Cambia o añade una clave conservando el resto (comentarios incluidos). Devuelve las líneas nuevas."""
    lines = list(lines)
    done = False
    pat = re.compile(r"^\s*#?\s*%s\s*=" % re.escape(key))
    for i, line in enumerate(lines):
        if pat.match(line) and not done:
            lines[i] = "%s=%s" % (key, value)
            done = True
    if not done:
        lines.append("%s=%s" % (key, value))
    return lines


def write_env_value(key, value):
    src = ENV_FILE if os.path.exists(ENV_FILE) else ENV_EXAMPLE
    with open(src, encoding="utf-8") as f:
        lines = f.read().splitlines()
    lines = set_env_value(lines, key, value)
    with open(ENV_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def new_password(length=20):
    return "".join(secrets.choice(PASSWORD_CHARS) for _ in range(length))


# ---------------------------------------------------------------- settings.json de Claude Code
def load_settings(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            raw = f.read().strip()
        if raw:
            return json.loads(raw)
    return {}


def write_settings(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def telemetry_changes(settings):
    """[(clave, valor viejo o None, valor nuevo)] de lo que cambiaría en settings.json."""
    env = settings.get("env") or {}
    changes = []
    for k, v in TELEMETRY_ENV.items():
        cur = env.get(k)
        if cur is None or str(cur) != v:
            changes.append((k, cur, v))
    return changes


def apply_telemetry(settings):
    settings.setdefault("env", {})
    for k, v in TELEMETRY_ENV.items():
        settings["env"][k] = v
    return settings


def remove_telemetry(settings):
    """Quita solo las variables del instalador que sigan con su valor. Devuelve (settings, claves quitadas)."""
    env = settings.get("env")
    if not isinstance(env, dict):
        return settings, []
    removed = [k for k, v in TELEMETRY_ENV.items() if str(env.get(k)) == v]
    for k in removed:
        del env[k]
    if not env:
        settings.pop("env", None)
    return settings, removed


def backup_settings(path):
    if not os.path.exists(path):
        return
    bk = os.path.join(ROOT, "installer", "backups")
    os.makedirs(bk, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, os.path.join(bk, "settings.json.%s.bak" % stamp))
    say("Copia guardada en installer/backups")


def configure_telemetry():
    path = os.path.join(CLAUDE_DIR, "settings.json")
    settings = load_settings(path)
    changes = telemetry_changes(settings)
    if not changes:
        say("La telemetría de Claude Code ya está configurada.", "green")
        return
    say("")
    say("Para medir Claude Code hay que activar su telemetría en %s :" % shown(path), "cyan")
    for k, old, new in changes:
        say("  + %s=%s" % (k, new) if old is None else "  ~ %s=%s  ->  %s" % (k, old, new))
    if not ask_yes_no("¿Aplico estos cambios? (se guarda antes una copia)"):
        say("No se ha tocado settings.json. Sin telemetría no habrá coste por llamada; "
            "consulta docs/claude-code.md para hacerlo a mano.", "yellow")
        return
    backup_settings(path)
    write_settings(path, apply_telemetry(settings))
    say("Telemetría activada. Reinicia Claude Code para que empiece a enviar datos.", "green")


def configure_retention():
    path = os.path.join(CLAUDE_DIR, "settings.json")
    settings = load_settings(path)
    current = int(settings.get("cleanupPeriodDays", 30))
    if current >= RETENTION_DAYS:
        return
    say("")
    say("Claude Code borra las conversaciones de más de %d días (cleanupPeriodDays)." % current, "cyan")
    say("IA-metrics guarda el uso de cada sesión en cuanto la lee, así que solo pierdes lo que Claude Code")
    say("borre mientras la pila está parada. Subirlo a %d días da más margen, pero conserva más tiempo en" % RETENTION_DAYS)
    say("disco el texto completo de las conversaciones (código, datos, lo que pegues en el prompt).")
    if not ask_yes_no("¿Subir cleanupPeriodDays a %d días? (se guarda antes una copia)" % RETENTION_DAYS, default=False):
        return
    backup_settings(path)
    settings["cleanupPeriodDays"] = RETENTION_DAYS
    write_settings(path, settings)
    say("cleanupPeriodDays = %d." % RETENTION_DAYS, "green")


def remove_claude_telemetry(force=False):
    path = os.path.join(CLAUDE_DIR, "settings.json")
    if not os.path.exists(path):
        return
    settings = load_settings(path)
    env = settings.get("env")
    present = [k for k in TELEMETRY_ENV if isinstance(env, dict) and str(env.get(k)) == TELEMETRY_ENV[k]]
    if not present:
        say("settings.json no tiene las variables de telemetría del instalador.")
        return
    say("")
    say("Variables de telemetría que añadió el instalador en %s :" % shown(path), "cyan")
    for k in present:
        say("  - %s" % k)
    if not (force or ask_yes_no("¿Las quito? (se guarda antes una copia)")):
        say("settings.json no se ha tocado.", "yellow")
        return
    backup_settings(path)
    settings, _ = remove_telemetry(settings)
    write_settings(path, settings)
    say("Telemetría desactivada. Reinicia Claude Code para que deje de enviar datos.", "green")


# ---------------------------------------------------------------- selección de herramientas
def parse_tools(text, names=("claude", "opencode")):
    """'1,3' / 'claude,opencode' -> lista ordenada y sin repetidos. Lanza ValueError si algo no vale."""
    table = {"1": "claude", "2": "opencode", "3": None}  # 3 = ambos
    out = []
    for x in re.split(r"[,;\s]+", text.strip()):
        if not x:
            continue
        if x == "3":
            out += ["claude", "opencode"]
        elif x in table and table[x]:
            out.append(table[x])
        elif x in names:
            out.append(x)
        else:
            raise ValueError("Opción no válida: %s" % x)
    return sorted(set(out))


def select_tools():
    has_claude = os.path.isdir(os.path.join(CLAUDE_DIR, "projects"))
    has_open = opencode_present()
    say("")
    say("¿Qué quieres medir?", "cyan")
    say("  1) Claude Code   %s" % ("(detectado)" if has_claude else "(no detectado)"))
    say("  2) OpenCode      %s" % ("(detectado)" if has_open else "(no detectado)"))
    say("  3) Ambos")
    default = "3" if (has_claude and has_open) else ("2" if has_open else "1")
    try:
        a = input("Elige 1, 2 o 3 [%s] " % default).strip() or default
    except EOFError:
        a = default
    return parse_tools(a)


# ---------------------------------------------------------------- zona horaria
def iana_timezone():
    """El nombre IANA de la zona horaria del equipo, o None si no se puede determinar."""
    # Modo delegado: la da el lanzador (el contenedor está en UTC y no ve la del equipo)
    host = os.environ.get("HOST_TZ", "").strip()
    if host:
        return host
    win_host = os.environ.get("HOST_TZ_WINDOWS", "").strip()
    if win_host:
        return WINDOWS_TO_IANA.get(win_host)
    if DELEGATED:
        return None
    if not IS_WINDOWS:
        link = "/etc/localtime"
        if os.path.islink(link):
            target = os.readlink(link)
            m = re.search(r"zoneinfo/(.+)$", target)
            if m:
                return m.group(1)
        tzfile = "/etc/timezone"
        if os.path.exists(tzfile):
            with open(tzfile) as f:
                name = f.read().strip()
            if name:
                return name
        return os.environ.get("TZ") or None
    try:
        win_id = subprocess.run(["tzutil", "/g"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        win_id = ""
    return WINDOWS_TO_IANA.get(win_id)


# ---------------------------------------------------------------- Docker
def docker_available():
    try:
        return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def start_docker_if_needed():
    if DELEGATED:   # el lanzador ya lo arrancó: sin Docker no habría contenedor
        return
    if shutil.which("docker") is None:
        raise SystemExit("No se encuentra Docker. Instala Docker Desktop (o Rancher Desktop / Podman con "
                         "docker compose) y vuelve a ejecutar el instalador.")
    if docker_available():
        return
    if IS_WINDOWS:
        dd = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Docker", "Docker", "Docker Desktop.exe")
        if os.path.exists(dd):
            say("Docker no está en marcha. Iniciando Docker Desktop...")
            subprocess.Popen([dd])
    elif IS_MAC:
        say("Docker no está en marcha. Iniciando Docker...")
        subprocess.Popen(["open", "-a", "Docker"])
    else:
        say("Docker no está en marcha. Arráncalo (por ejemplo: sudo systemctl start docker) y espero...", "yellow")
    for n in range(1, 37):
        time.sleep(5)
        if docker_available():
            return
        say("Esperando a Docker... (%d/36)" % n)
    raise SystemExit("Docker no arrancó a tiempo. Ábrelo a mano y vuelve a ejecutar el instalador.")


def compose(*args, check=True, quiet=False):
    kw = {"cwd": ROOT}
    if quiet:
        kw["stdout"] = subprocess.DEVNULL
        kw["stderr"] = subprocess.DEVNULL
    r = subprocess.run(["docker", "compose", *args], **kw)
    if check and r.returncode != 0:
        raise SystemExit("Falló: docker compose %s" % " ".join(args))
    return r.returncode


# ---------------------------------------------------------------- migración de pilas antiguas
def _project_containers(project):
    r = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "label=com.docker.compose.project=%s" % project],
                       capture_output=True, text=True)
    return [x for x in r.stdout.split() if x]


def _volume_empty(name):
    r = subprocess.run(["docker", "run", "--rm", "-v", "%s:/v" % name, "alpine:3.20", "sh", "-c", "ls -A /v | head -1"],
                       capture_output=True, text=True)
    return not r.stdout.strip()


def _copy_volume(src, dst):
    subprocess.run(["docker", "volume", "create", dst], stdout=subprocess.DEVNULL, check=True)
    if not _volume_empty(dst):
        say("  %s ya tiene datos: no se sobrescribe." % dst, "yellow")
        return
    r = subprocess.run(["docker", "run", "--rm", "-v", "%s:/from:ro" % src, "-v", "%s:/to" % dst,
                        "alpine:3.20", "sh", "-c", "cp -a /from/. /to/"])
    if r.returncode != 0:
        raise SystemExit("No se pudo copiar %s a %s" % (src, dst))
    say("  %s -> %s" % (src, dst))


def migrate(selected, force=False):
    volumes = subprocess.run(["docker", "volume", "ls", "-q"], capture_output=True, text=True).stdout.split()
    old = [p for p in ("claude-metrics", "opencode-metrics")
           if _project_containers(p) or any(v.startswith(p) for v in volumes)]
    if not old:
        return
    say("")
    say("Se han encontrado las pilas anteriores: %s." % ", ".join(old), "cyan")
    say("Usan los mismos puertos que IA-metrics, así que hay que pararlas. Sus volúmenes no se borran.")
    if not (force or ask_yes_no("¿Las paro y migro su historial a IA-metrics?")):
        say("Sin parar las pilas antiguas, la nueva no podrá arrancar por conflicto de puertos.", "yellow")
        return
    for p in old:
        c = _project_containers(p)
        if c:
            subprocess.run(["docker", "stop", *c], stdout=subprocess.DEVNULL)
            say("  Parada la pila %s" % p)
    if "claude" in selected:
        for v in MIGRATE_VOLUMES:
            if ("claude-metrics_%s" % v) in volumes:
                _copy_volume("claude-metrics_%s" % v, "ia-metrics_%s" % v)


# ---------------------------------------------------------------- acceso directo (opcional, por SO)
def make_shortcut():
    try:
        if IS_WINDOWS:
            desktop = os.path.join(HOME, "Desktop")
            lnk = os.path.join(desktop, "IA-metrics.lnk")
            target = os.path.join(ROOT, "Iniciar-metricas.bat")
            ico = os.path.join(ROOT, "installer", "metricas.ico")
            ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
                  "$s.TargetPath='%s';$s.WorkingDirectory='%s';%s$s.Save()"
                  % (lnk, target, ROOT, ("$s.IconLocation='%s';" % ico) if os.path.exists(ico) else ""))
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(lnk):
                say("Acceso directo creado en el escritorio: %s" % lnk)
        elif not IS_MAC:  # Linux: lanzador .desktop
            apps = os.path.join(HOME, ".local", "share", "applications")
            os.makedirs(apps, exist_ok=True)
            path = os.path.join(apps, "ia-metrics.desktop")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\nType=Application\nName=IA-metrics\n"
                        "Exec=%s\nTerminal=true\nCategories=Development;\n"
                        % os.path.join(ROOT, "iniciar-metricas.sh"))   # usa Python o el contenedor (ADR 0009)
            say("Lanzador creado: %s" % path)
    except Exception as e:  # el acceso directo es un extra: un fallo no corta la instalación
        say("No se pudo crear el acceso directo (%s)." % type(e).__name__, "yellow")


def remove_shortcut():
    for path in (os.path.join(HOME, "Desktop", "IA-metrics.lnk"),
                 os.path.join(HOME, ".local", "share", "applications", "ia-metrics.desktop")):
        if os.path.exists(path):
            os.remove(path)
            say("Acceso directo eliminado: %s" % path)


# ---------------------------------------------------------------- arrancar
def wait_healthy():
    say("Esperando a que los servicios estén listos...")
    if compose("up", "-d", "--wait", "--wait-timeout", "180", check=False, quiet=True) != 0:
        say("Algún servicio no está sano todavía. Revísalo con: docker compose ps", "yellow")


def check_prices(tools):
    """Aviso best-effort de modelos sin precio, como Iniciar-metricas.bat, pero en los tres SO."""
    import urllib.request
    for tool, port in (("claude", 9100), ("opencode", 9101)):
        if tools is not None and tool not in tools:
            continue
        status = ""
        for _ in range(4):  # el colector puede estar en su primera lectura (PENDIENTE); se espera un poco
            try:
                status = urllib.request.urlopen("http://localhost:%d/prices/missing" % port, timeout=4).read().decode()
            except Exception:
                break
            if status.startswith(("OK", "SIN")):
                break
            time.sleep(5)
        if status.startswith("SIN"):
            say("")
            say("AVISO (%s): modelos sin precio; su coste no cuenta en el dashboard:" % tool, "yellow")
            print(status.split("\n", 1)[-1].rstrip())
            say("Detalle: http://localhost:%d/prices" % port)


def do_start(tools=None, open_browser=True):
    start_docker_if_needed()
    say("Levantando IA-metrics...")
    compose("up", "-d", "--remove-orphans")
    wait_healthy()
    say("")
    say("Listo.", "green")
    say("  Grafana:            http://localhost:3000  (usuario admin)")
    if tools is None or "claude" in tools:
        say("  Sesiones Claude:    http://localhost:9100/sessions")
    if tools is None or "opencode" in tools:
        say("  Sesiones OpenCode:  http://localhost:9101/sessions")
    try:
        check_prices(tools)
    except Exception:
        pass
    if open_browser:
        try:
            webbrowser.open("http://localhost:3000")
        except Exception:
            pass


# ---------------------------------------------------------------- modos
def invoke_update(force=False):
    say("== Actualizar IA-metrics ==", "cyan")
    start_docker_if_needed()
    if os.path.isdir(os.path.join(ROOT, ".git")) and shutil.which("git"):
        remote = subprocess.run(["git", "remote"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if not remote:
            say("El repositorio no tiene remoto: no se descarga código nuevo.")
        elif dirty:
            say("Hay cambios locales sin commit: no se descarga código nuevo (git pull) para no mezclarlos.", "yellow")
        elif force or ask_yes_no("¿Descargo la última versión del código? (git pull --ff-only)"):
            if subprocess.run(["git", "pull", "--ff-only"], cwd=ROOT).returncode != 0:
                say("git pull no pudo avanzar (ramas divergentes o sin red): se sigue con el código actual.", "yellow")
    say("Descargando las imágenes de Docker...")
    compose("pull")
    compose("up", "-d", "--remove-orphans")
    wait_healthy()
    say("IA-metrics actualizado. El historial se conserva.", "green")


def invoke_uninstall(remove_data=False, force=False):
    say("== Desinstalar IA-metrics ==", "cyan")
    say("Se pararán y eliminarán los contenedores de IA-metrics. La carpeta del proyecto y .env no se borran.")
    if not (force or ask_yes_no("¿Continuar?", default=False)):
        say("Cancelado.", "yellow")
        return
    if not remove_data and not force:
        remove_data = ask_yes_no("¿Borrar también el historial (volúmenes de Prometheus, Loki, Grafana y "
                                 "coach.db)? No se puede deshacer.", default=False)
    if DELEGATED:   # los contenedores y el acceso directo los quita el lanzador al terminar
        host_action("DOWN")
        if remove_data:
            host_action("REMOVE_DATA")
        remove_claude_telemetry(force)
        host_action("REMOVE_SHORTCUT")
        return
    start_docker_if_needed()
    args = ["--profile", "claude", "--profile", "opencode", "down", "--remove-orphans"]
    if remove_data:
        args.append("-v")
    compose(*args)
    if remove_data:
        say("Contenedores y volúmenes eliminados.", "green")
    else:
        say("Contenedores eliminados; el historial sigue en los volúmenes ia-metrics_* (se recupera al reinstalar).", "green")
    remove_claude_telemetry(force)
    remove_shortcut()
    say("")
    say("IA-metrics desinstalado. Para quitarlo del todo, borra la carpeta del proyecto.", "green")


def do_install(args):
    say("== Instalador de IA-metrics ==", "cyan")
    start_docker_if_needed()
    tools = parse_tools(args.tools) if args.tools else select_tools()
    profiles = ",".join(tools)
    say("Herramientas: %s" % profiles, "green")

    env = read_env_file()
    pw = env.get("GRAFANA_ADMIN_PASSWORD", "")
    if pw in ("", "change-me", "change_me"):
        pw = new_password()
        write_env_value("GRAFANA_ADMIN_PASSWORD", pw)
        say("Contraseña de Grafana generada (usuario admin): %s" % pw, "yellow")
        say("Guárdala: también está en el fichero .env.")
    write_env_value("COMPOSE_PROFILES", profiles)
    if "TZ" not in read_env_file():
        tz = iana_timezone()
        if tz:
            write_env_value("TZ", tz)
            say("Zona horaria: %s" % tz)
        else:
            say("No se pudo determinar la zona horaria; se usa Europe/Madrid. Cámbiala con TZ en .env.", "yellow")

    if "claude" in tools:
        if not os.path.isdir(os.path.join(CLAUDE_DIR, "projects")):
            say("Aviso: no existe ~/.claude/projects; ¿has usado Claude Code en este equipo?", "yellow")
        for d in ("projects", "commands", "skills"):
            os.makedirs(os.path.join(CLAUDE_DIR, d), exist_ok=True)
        if not args.skip_claude_settings:
            configure_telemetry()
            configure_retention()
    if "opencode" in tools:
        if not opencode_present():
            say("Aviso: no se encuentra %s. Si OpenCode guarda sus datos en otra carpeta, define "
                "OPENCODE_DATA_DIR en .env." % shown(OPENCODE_DB), "yellow")
        if DELEGATED:   # el contenedor no ve esas carpetas: las crea el lanzador
            host_action("OPENCODE_DIRS")
        else:
            os.makedirs(os.path.join(HOME, ".config", "opencode", "commands"), exist_ok=True)
            os.makedirs(os.path.join(HOME, ".cache", "opencode"), exist_ok=True)

    if not args.skip_migration:
        if DELEGATED:
            say("Sin Python en el equipo no se migran las pilas antiguas (claude-metrics, opencode-metrics). Si las "
                "tienes, páralas con «docker compose down» en su carpeta o instala Python 3 y repite.", "yellow")
        else:
            migrate(tools, args.force)
    if not args.no_shortcut:
        if DELEGATED:
            host_action("SHORTCUT")
        else:
            make_shortcut()
    if args.no_start:
        say("Instalación lista. Arranca con Iniciar-metricas.bat (Windows) o ./iniciar-metricas.sh.", "green")
        return
    if DELEGATED:   # el lanzador para los dos perfiles y levanta los elegidos
        host_action("START")
        return
    # quita los servicios del perfil que ya no se usa y levanta los elegidos
    compose("--profile", "claude", "--profile", "opencode", "stop", check=False, quiet=True)
    do_start(tools)


def main(argv=None):
    p = argparse.ArgumentParser(description="Instalador multiplataforma de IA-metrics.")
    p.add_argument("--tools", help="claude, opencode o claude,opencode (sin preguntar)")
    p.add_argument("--no-start", action="store_true")
    p.add_argument("--skip-claude-settings", action="store_true")
    p.add_argument("--skip-migration", action="store_true")
    p.add_argument("--no-shortcut", action="store_true")
    p.add_argument("--update", action="store_true")
    p.add_argument("--uninstall", action="store_true")
    p.add_argument("--remove-data", action="store_true")
    p.add_argument("--start", action="store_true", help="solo arrancar la pila y abrir Grafana")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)
    if args.update and args.uninstall:
        p.error("Usa --update o --uninstall, no los dos.")
    if args.remove_data and not args.uninstall:
        p.error("--remove-data solo vale con --uninstall.")
    if DELEGATED and (args.update or args.start):
        p.error("--update y --start no usan el contenedor: los hace el lanzador (installer/run.bat, installer/run.sh).")
    try:
        if args.update:
            invoke_update(args.force)
        elif args.uninstall:
            invoke_uninstall(args.remove_data, args.force)
        elif args.start:
            do_start()
        else:
            do_install(args)
    except KeyboardInterrupt:
        say("\nCancelado.", "yellow")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

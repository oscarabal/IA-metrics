"""Static checks of compose, Prometheus, Grafana provisioning and dashboards."""
import glob
import json
import os
import re
import shutil
import subprocess
import unittest

import helpers

try:
    import yaml
except ImportError:  # PyYAML is only needed here; CI installs it
    yaml = None

R = helpers.ROOT


def load_yaml(path):
    with open(os.path.join(R, path), encoding="utf-8") as f:
        return yaml.safe_load(f)


def dashboards():
    for path in sorted(glob.glob(os.path.join(R, "grafana", "dashboards", "*", "*.json"))):
        with open(path, encoding="utf-8") as f:
            yield path, json.load(f)


def panels(d):
    def walk(p):
        yield p
        for c in p.get("panels", []):
            yield from walk(c)
    for p in d.get("panels", []):
        yield from walk(p)


def targets(d):
    for p in panels(d):
        for t in p.get("targets", []):
            yield p, t
    for v in d.get("templating", {}).get("list", []):
        yield v, v


@unittest.skipIf(yaml is None, "PyYAML no instalado")
class Compose(unittest.TestCase):
    def setUp(self):
        self.c = load_yaml("docker-compose.yml")

    def test_profiles(self):
        prof = {n: tuple(s.get("profiles", ())) for n, s in self.c["services"].items()}
        self.assertEqual(prof["prometheus"], ())
        self.assertEqual(prof["grafana"], ())
        for n in ("otel-collector", "loki", "claude-collector"):
            self.assertEqual(prof[n], ("claude",), n)
        self.assertEqual(prof["opencode-collector"], ("opencode",))

    def test_images_pinned(self):
        for n, s in self.c["services"].items():
            self.assertNotRegex(s["image"], r":latest$|^[^:]+$", n)

    def test_healthchecks(self):
        """Prometheus, Grafana and both collectors report their health; Grafana waits for Prometheus."""
        for n in ("prometheus", "grafana", "claude-collector", "opencode-collector"):
            self.assertIn("healthcheck", self.c["services"][n], n)
            self.assertTrue(self.c["services"][n]["healthcheck"]["test"], n)
        self.assertEqual(self.c["services"]["grafana"]["depends_on"]["prometheus"]["condition"], "service_healthy")
        for n, port in (("claude-collector", 9100), ("opencode-collector", 9101)):
            self.assertIn("http://127.0.0.1:%d/health" % port, " ".join(self.c["services"][n]["healthcheck"]["test"]))

    def test_grafana_supported_branch(self):
        """Grafana 12.1 is out of support (April 2026): keep a 13.x or later image."""
        major = int(self.c["services"]["grafana"]["image"].split(":")[1].split(".")[0])
        self.assertGreaterEqual(major, 13)

    def test_ports_loopback_only(self):
        for n, s in self.c["services"].items():
            for p in s.get("ports", []):
                self.assertTrue(str(p).startswith("127.0.0.1:"), "%s publica %s" % (n, p))

    def test_logs_capped(self):
        for n, s in self.c["services"].items():
            self.assertIn("max-size", s.get("logging", {}).get("options", {}), n)

    def test_privacy_mounts(self):
        mounts = " ".join(self.c["services"]["claude-collector"]["volumes"])
        self.assertNotIn("settings.json", mounts)
        for v in self.c["services"]["claude-collector"]["volumes"]:
            if ".claude}" in v:
                self.assertRegex(v, r"\.claude\}/(projects|commands|skills):.*:ro$")

    def test_prometheus_targets_exist(self):
        prom = load_yaml("config/prometheus/prometheus.yml")
        for job in prom["scrape_configs"]:
            for sc in job["static_configs"]:
                for t in sc["targets"]:
                    self.assertIn(t.split(":")[0], self.c["services"], t)

    def test_collector_ports_match_prometheus(self):
        prom = load_yaml("config/prometheus/prometheus.yml")
        wanted = {t for j in prom["scrape_configs"] for sc in j["static_configs"] for t in sc["targets"]}
        self.assertIn("claude-collector:9100", wanted)
        self.assertIn("opencode-collector:9101", wanted)

    def test_otel_exporters_defined(self):
        """Every exporter a pipeline references must exist in `exporters` (a typo like `otlp_http/loki`
        for `otlphttp/loki` made the collector refuse to start, 2026-11-21)."""
        cfg = load_yaml("config/otel-collector.yaml")
        defined = set(cfg["exporters"])
        for name, pipe in cfg["service"]["pipelines"].items():
            for exp in pipe.get("exporters", []):
                self.assertIn(exp, defined, "pipeline %s usa un exportador no definido: %s" % (name, exp))

    def test_telemetry_pipeline_observed(self):
        """«Estado de las fuentes»: Prometheus reads the collector's internal metrics and Loki's, which stay unpublished."""
        prom = load_yaml("config/prometheus/prometheus.yml")
        wanted = {t for j in prom["scrape_configs"] for sc in j["static_configs"] for t in sc["targets"]}
        self.assertTrue({"otel-collector:8888", "loki:3100"} <= wanted)
        reader = load_yaml("config/otel-collector.yaml")["service"]["telemetry"]["metrics"]["readers"][0]["pull"]["exporter"]["prometheus"]
        self.assertEqual((reader["host"], reader["port"]), ("0.0.0.0", 8888))
        published = " ".join(str(p) for s in self.c["services"].values() for p in s.get("ports", []))
        self.assertNotIn("8888", published)


@unittest.skipIf(yaml is None, "PyYAML no instalado")
class Grafana(unittest.TestCase):
    def setUp(self):
        self.ds = {d["uid"]: d for d in load_yaml("config/grafana/datasources.yaml")["datasources"]}

    def test_dashboard_uids_unique(self):
        uids = [d["uid"] for _p, d in dashboards()]
        self.assertEqual(len(uids), len(set(uids)))

    def test_datasources_exist(self):
        for path, d in dashboards():
            for p, t in targets(d):
                ds = t.get("datasource") or p.get("datasource")
                uid = ds.get("uid") if isinstance(ds, dict) else None
                if uid and not uid.startswith("$") and uid not in ("-- Grafana --", "grafana", "-- Mixed --", "-- Dashboard --"):
                    self.assertIn(uid, self.ds, "%s: %s" % (os.path.basename(path), p.get("title") or p.get("name")))

    def test_infinity_urls_allowed(self):
        for path, d in dashboards():
            for p, t in targets(d):
                ds = t.get("datasource") or p.get("datasource") or {}
                if not isinstance(ds, dict) or ds.get("type") != "yesoreyeram-infinity-datasource":
                    continue
                url = t.get("url") or (t.get("query") or {}).get("url") if isinstance(t.get("query"), dict) else t.get("url")
                if not url:
                    continue
                allowed = self.ds[ds["uid"]]["jsonData"]["allowedHosts"]
                self.assertTrue(any(url.startswith(a) for a in allowed), "%s: %s -> %s" % (os.path.basename(path), p.get("title"), url))

    def test_field_filter_not_defeated_by_renames(self):
        """Grafana applies displayName overrides before reduceOptions.fields: a panel that renames its
        fields and then picks them by their original name shows "No data"."""
        for path, d in dashboards():
            for p in panels(d):
                fields = ((p.get("options") or {}).get("reduceOptions") or {}).get("fields") or ""
                if not fields:
                    continue
                renames = [o for o in (p.get("fieldConfig") or {}).get("overrides", [])
                           if any(pr.get("id") == "displayName" for pr in o.get("properties", []))]
                for o in renames:
                    m = o.get("matcher", {})
                    hit = m.get("id") == "byFrameRefID" or (m.get("id") == "byName" and re.fullmatch(fields.strip("/").replace("\\", "\\"), m.get("options", "")))
                    self.assertFalse(hit, "%s: «%s» filtra %s pero renombra ese campo" % (os.path.basename(path), p.get("title"), fields))

    def test_long_no_value_not_in_narrow_cells(self):
        """fieldConfig.defaults.noValue also fills every empty cell: a sentence in a narrow column makes
        the whole row as tall as the wrapped sentence. Narrow columns must set their own noValue."""
        for path, d in dashboards():
            for p in panels(d):
                if p.get("type") != "table":
                    continue
                text = ((p.get("fieldConfig") or {}).get("defaults") or {}).get("noValue") or ""
                if len(text) <= 3:
                    continue
                for o in (p.get("fieldConfig") or {}).get("overrides", []):
                    props = {pr.get("id"): pr.get("value") for pr in o.get("properties", [])}
                    if (props.get("custom.width") or 999) < 120:
                        self.assertIn("noValue", props, "%s: «%s», columna %s" % (os.path.basename(path), p.get("title"),
                                                                                    o.get("matcher", {}).get("options")))

    def test_table_rows_one_line(self):
        """Wrapped cells make Grafana size each row for its longest text: tables stay one line per row."""
        for path, d in dashboards():
            for p in panels(d):
                if p.get("type") == "table":
                    co = (((p.get("fieldConfig") or {}).get("defaults") or {}).get("custom") or {}).get("cellOptions") or {}
                    self.assertFalse(co.get("wrapText"), "%s: «%s»" % (os.path.basename(path), p.get("title")))
                    self.assertNotEqual((p.get("options") or {}).get("cellHeight"), "lg", p.get("title"))

    def test_no_legacy_names(self):
        for path, d in dashboards():
            text = json.dumps(d)
            for bad in ("session-map:", "exporter:9101", '"uid": "coach"', "localhost:3001"):
                self.assertNotIn(bad, text, os.path.basename(path))


class Installer(unittest.TestCase):
    """El instalador es install.py (un solo fichero para Windows, macOS y Linux). Los .bat y .sh llaman a
    installer/run.bat o installer/run.sh, que usan Python si está y, si no, install.py en un contenedor (ADR 0009).
    Las funciones de install.py se prueban en tests/test_installer.py."""

    BAT = (("Instalar.bat", "install"), ("Actualizar.bat", "update"), ("Desinstalar.bat", "uninstall"))
    SH = (("instalar.sh", "install"), ("actualizar.sh", "update"), ("desinstalar.sh", "uninstall"),
          ("iniciar-metricas.sh", "start"))

    def read(self, *rel, encoding="utf-8"):
        with open(os.path.join(R, *rel), encoding=encoding) as f:
            return f.read()

    def test_entry_points_call_the_launcher(self):
        for name, mode in self.BAT:
            bat = self.read(name, encoding="ascii")
            self.assertIn(r"installer\run.bat", bat, name)
            self.assertIn('set "IA_METRICS_MODE=%s"' % mode, bat, name)
        for name, mode in self.SH:
            self.assertIn("installer/run.sh\" %s" % mode, self.read(name), name)

    def test_launchers_call_install_py_with_each_mode(self):
        bat, sh = self.read("installer", "run.bat", encoding="ascii"), self.read("installer", "run.sh")
        for flag in ("--update", "--uninstall"):
            self.assertIn(r"installer\install.py " + flag, bat, flag)
            self.assertIn("installer/install.py " + flag, sh, flag)
        self.assertIn("installer/install.py --start", sh)

    def test_container_uses_the_collectors_image(self):
        """Sin Python, install.py corre en la misma imagen que los colectores: no se descarga otra."""
        image = load_yaml(os.path.join(R, "docker-compose.yml"))["x-collector"]["image"]
        self.assertIn('set "PY_IMAGE=%s"' % image, self.read("installer", "run.bat", encoding="ascii"))
        self.assertIn('PY_IMAGE="%s"' % image, self.read("installer", "run.sh"))

    def test_launchers_handle_every_host_action(self):
        """Cada paso que install.py deja al lanzador en modo delegado lo atienden los dos lanzadores."""
        keys = set(re.findall(r'host_action\("([A-Z_]+)"\)', self.read("installer", "install.py")))
        self.assertEqual(keys, {"START", "SHORTCUT", "OPENCODE_DIRS", "DOWN", "REMOVE_DATA", "REMOVE_SHORTCUT"})
        bat, sh = self.read("installer", "run.bat", encoding="ascii"), self.read("installer", "run.sh")
        for k in keys:
            self.assertIn("HA_" + k, bat, k)
            self.assertIn("action " + k, sh, k)
        self.assertIn("installer/.host-actions", self.read(".gitignore"))

    def test_update_restarts_the_services(self):
        """`up -d` solo recrea lo que cambia en docker-compose.yml: el código de los colectores y la configuración
        montados no se recargan. Actualizar reinicia los servicios después de `up -d` y antes de esperar a que estén
        sanos, con Python (install.py) y sin él (run.bat, run.sh)."""
        sources = {
            "install.py": (self.read("installer", "install.py"),
                           ('compose("up", "-d", "--remove-orphans")', "restart_services()", "wait_healthy()"),
                           "def invoke_update"),
            "run.bat": (self.read("installer", "run.bat", encoding="ascii"),
                        ("docker compose up -d --remove-orphans", "docker compose restart", "--wait"), ":docker_update"),
            "run.sh": (self.read("installer", "run.sh"),
                       ("docker compose up -d --remove-orphans", "docker compose restart", "--wait"), "== Actualizar IA-metrics =="),
        }
        for name, (text, steps, start) in sources.items():
            section = text[text.index(start):]
            positions = [section.index(step) for step in steps]
            self.assertEqual(positions, sorted(positions), "%s: %s" % (name, positions))
        self.assertIn('compose("restart"', self.read("installer", "install.py"))

    def test_install_py_has_modes(self):
        src = self.read("installer", "install.py")
        for flag in ("--tools", "--update", "--uninstall", "--remove-data", "--start", "--force", "--no-start"):
            self.assertIn(flag, src, flag)

    def test_no_powershell_installer(self):
        """El instalador de PowerShell se retiró: nada debe seguir apuntando a install.ps1."""
        self.assertFalse(os.path.exists(os.path.join(R, "installer", "install.ps1")))
        for name in ("Instalar.bat", "Actualizar.bat", "Desinstalar.bat", os.path.join("installer", "run.bat")):
            self.assertNotIn("install.ps1", self.read(name, encoding="ascii"), name)

    def test_line_endings(self):
        """Windows necesita CRLF en los .bat; los .sh de Unix van con LF."""
        for rel in ("Instalar.bat", "Iniciar-metricas.bat", "Actualizar.bat", "Desinstalar.bat",
                    os.path.join("installer", "run.bat")):
            with open(os.path.join(R, rel), "rb") as f:
                data = f.read()
            self.assertNotRegex(data, re.compile(rb"[^\r]\n"), rel)
        for rel in ("instalar.sh", "actualizar.sh", "desinstalar.sh", "iniciar-metricas.sh",
                    os.path.join("installer", "run.sh")):
            with open(os.path.join(R, rel), "rb") as f:
                data = f.read()
            self.assertNotIn(b"\r\n", data, rel)

    def test_shell_syntax(self):
        if not shutil.which("bash"):
            self.skipTest("sin bash")
        for rel in ("instalar.sh", "actualizar.sh", "desinstalar.sh", "iniciar-metricas.sh",
                    os.path.join("installer", "run.sh")):
            r = subprocess.run(["bash", "-n", os.path.join(R, rel)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, rel + r.stderr)


if __name__ == "__main__":
    unittest.main()

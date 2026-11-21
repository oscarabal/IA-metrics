"""El instalador multiplataforma install.py: funciones puras (sin Docker), en los tres SO."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "installer"))
import install  # noqa: E402


class ParseTools(unittest.TestCase):
    def test_numbers_and_names(self):
        self.assertEqual(install.parse_tools("1"), ["claude"])
        self.assertEqual(install.parse_tools("2"), ["opencode"])
        self.assertEqual(install.parse_tools("3"), ["claude", "opencode"])
        self.assertEqual(install.parse_tools("claude,opencode"), ["claude", "opencode"])

    def test_dedup_and_order(self):
        self.assertEqual(install.parse_tools("2,1,1"), ["claude", "opencode"])
        self.assertEqual(install.parse_tools("1 3"), ["claude", "opencode"])

    def test_invalid(self):
        with self.assertRaises(ValueError):
            install.parse_tools("9")


class EnvFile(unittest.TestCase):
    def test_update_commented_key(self):
        self.assertEqual(install.set_env_value(["A=1", "# B=2", "C=3"], "B", "9"), ["A=1", "B=9", "C=3"])

    def test_add_missing_key(self):
        self.assertEqual(install.set_env_value(["A=1"], "D", "x"), ["A=1", "D=x"])

    def test_only_first_match_changes(self):
        self.assertEqual(install.set_env_value(["K=1", "K=2"], "K", "3"), ["K=3", "K=2"])

    def test_write_preserves_comments(self):
        tmp = tempfile.mkdtemp()
        example = os.path.join(tmp, ".env.example")
        with open(example, "w") as f:
            f.write("# comentario\n# TZ=\nGRAFANA_ADMIN_PASSWORD=change-me\n")
        old = install.ENV_FILE, install.ENV_EXAMPLE
        install.ENV_FILE, install.ENV_EXAMPLE = os.path.join(tmp, ".env"), example
        try:
            install.write_env_value("TZ", "Europe/Madrid")
            install.write_env_value("COMPOSE_PROFILES", "claude")
            body = open(install.ENV_FILE, encoding="utf-8").read()
        finally:
            install.ENV_FILE, install.ENV_EXAMPLE = old
        self.assertIn("# comentario", body)
        self.assertIn("TZ=Europe/Madrid", body)
        self.assertIn("COMPOSE_PROFILES=claude", body)
        self.assertNotIn("\r\n", body)


class Telemetry(unittest.TestCase):
    def test_apply_then_no_changes(self):
        s = install.apply_telemetry({})
        self.assertEqual(install.telemetry_changes(s), [])
        self.assertEqual(s["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"], "1")

    def test_changes_lists_new_and_modified(self):
        s = {"env": {"OTEL_METRICS_EXPORTER": "console"}}
        keys = {c[0] for c in install.telemetry_changes(s)}
        self.assertIn("OTEL_METRICS_EXPORTER", keys)      # distinto -> cambia
        self.assertIn("CLAUDE_CODE_ENABLE_TELEMETRY", keys)  # ausente -> se añade

    def test_uninstall_removes_only_installer_vars(self):
        """Lo que comprobaba installer_uninstall.ps1: solo se quitan las variables del instalador que
        sigan con su valor; una cambiada, otras variables y el resto de settings se conservan."""
        s = {"model": "opus", "env": dict(install.TELEMETRY_ENV)}
        s["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://otro:4317"   # valor cambiado por el usuario
        s["env"]["MI_VAR"] = "x"
        s, removed = install.remove_telemetry(s)
        self.assertEqual(s["model"], "opus")
        self.assertEqual(sorted(s["env"]), ["MI_VAR", "OTEL_EXPORTER_OTLP_ENDPOINT"])
        self.assertNotIn("OTEL_EXPORTER_OTLP_ENDPOINT", removed)
        self.assertIn("CLAUDE_CODE_ENABLE_TELEMETRY", removed)

    def test_remove_empties_env(self):
        s = {"env": dict(install.TELEMETRY_ENV)}
        s, _ = install.remove_telemetry(s)
        self.assertNotIn("env", s)   # sin variables propias, se quita el bloque env

    def test_settings_roundtrip_utf8_no_bom(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "settings.json")
        install.write_settings(path, {"env": {"K": "ñ"}})
        with open(path, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))   # sin BOM
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(install.load_settings(path)["env"]["K"], "ñ")


class TimeZone(unittest.TestCase):
    def test_map_has_known_zones(self):
        self.assertEqual(install.WINDOWS_TO_IANA["Romance Standard Time"], "Europe/Madrid")

    def test_returns_name_or_none(self):
        tz = install.iana_timezone()   # no debe lanzar en ningún SO
        self.assertTrue(tz is None or "/" in tz or tz == "UTC")


if __name__ == "__main__":
    unittest.main()

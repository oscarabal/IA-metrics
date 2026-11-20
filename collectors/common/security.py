"""Host header check for the collectors' HTTP servers.

The collectors serve session titles, project names and the improvement report without
authentication, on 127.0.0.1 only. That alone does not stop DNS rebinding: a web page can make the
browser resolve its own domain to 127.0.0.1 and read these pages as same-origin. Browsers always send
the name the page used in the Host header, so accepting only known names closes that door.

Accepted: localhost, 127.0.0.1, [::1], the compose service names (Prometheus and Grafana's Infinity
datasource reach the collectors by them) and any extra name in ALLOWED_HOSTS (comma-separated).
"""
import os

DEFAULT_HOSTS = {"localhost", "127.0.0.1", "::1", "claude-collector", "opencode-collector"}
ALLOWED_HOSTS = DEFAULT_HOSTS | {h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}


def host_name(header):
    """'localhost:9100' -> 'localhost', '[::1]:9100' -> '::1'; None for a missing or empty header."""
    if not header:
        return None
    header = header.strip().lower()
    if header.startswith("["):
        end = header.find("]")
        return header[1:end] if end > 0 else None
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


def host_allowed(header):
    return host_name(header) in ALLOWED_HOSTS


def reject_unknown_host(handler):
    """Answer 421 and return True when the request's Host is not an accepted name."""
    if host_allowed(handler.headers.get("Host")):
        return False
    body = b"Host no permitido. Abre la pagina con http://localhost o anade el nombre a ALLOWED_HOSTS.\n"
    handler.send_response(421)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True

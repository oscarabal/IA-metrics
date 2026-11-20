"""ADR 0002: move the Claude Code dashboard's cost and per-day panels to the collector's /data API.

Run once from the repository root; it rewrites grafana/dashboards/claude/claude-code.json in place and
refuses to run twice. Titles, layout, units, colours and overrides stay as they were.

- Cost and token panels read the hybrid ledger (telemetry cost, else the price table) instead of the
  per-session OTel counters, so they cover every session in the conversation files.
- Per-day collector series (claude_day_*, claude_coach_*) become /data queries.
- Kept as they were: context (current state), the Loki panels (prompts, tools), the «Por hora» row
  (OTel), and the improvement report panels.
- New row «Diagnóstico del coste»: OTel counters against the ledger, and the price table against the
  telemetry for the requests that have both.
"""
import json
import os
import sys
import urllib.parse

PATH = os.path.join("grafana", "dashboards", "claude", "claude-code.json")
BASE = "http://claude-collector:9100/data/"
INF = {"type": "yesoreyeram-infinity-datasource", "uid": "coach-claude"}
PROM = {"type": "prometheus", "uid": "prometheus"}
MIXED = {"type": "datasource", "uid": "-- Mixed --"}
RANGE = "from=${__from}&to=${__to}&${project:queryparam}&${sessions:queryparam}"
TOK_M = "tokens_m:tokens/1000000"


def url(dataset, **params):
    extra = "&".join("%s=%s" % (k.replace("__", "."), urllib.parse.quote(str(v), safe=":,/()*-_.")) for k, v in params.items())
    return BASE + dataset + "?" + RANGE + ("&" + extra if extra else "")


def inf(ref, dataset, **params):
    return {"refId": ref, "datasource": INF, "type": "json", "source": "url", "format": "table", "parser": "backend",
            "url": url(dataset, **params), "url_options": {"method": "GET", "data": ""}, "root_selector": "", "columns": []}


def organize(rename, exclude=(), index=None):
    opts = {"excludeByName": {k: True for k in exclude}, "renameByName": rename}
    if index:
        opts["indexByName"] = index
    return {"id": "organize", "options": opts}


def sort(field, desc=False):
    return {"id": "sortBy", "options": {"sort": [{"field": field, "desc": desc}]}}


def to_time(field):
    return {"id": "convertFieldType", "options": {"conversions": [{"targetField": field, "destinationType": "time"}]}}


def stat(p, target, field):
    p["datasource"], p["targets"] = INF, [target]
    p.setdefault("options", {}).setdefault("reduceOptions", {})["fields"] = "/^%s$/" % field


def bars(p, target, field):
    p["datasource"], p["targets"] = INF, [target]
    p.setdefault("options", {})["reduceOptions"] = {"values": True, "calcs": [], "fields": "/^%s$/" % field}


def display(name, text):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "displayName", "value": text}]}


def migrate(d):
    by_id = {}

    def walk(p):
        by_id[p["id"]] = p
        for c in p.get("panels", []):
            walk(c)
    for p in d["panels"]:
        walk(p)
    otel_cost = by_id[2]["targets"][0]["expr"]   # kept for the diagnostic row

    # ------------------------------------------------------------------ Resumen
    stat(by_id[2], inf("A", "usage", measures="cost"), "cost")
    stat(by_id[3], inf("A", "usage", measures="tokens", calc=TOK_M), "tokens_m")
    stat(by_id[4], inf("A", "usage", measures="cost,tokens", calc="usd_mtok:cost/(tokens/1000000)"), "usd_mtok")
    stat(by_id[5], inf("A", "usage", measures="input,cache_read,cache_write",
                       calc="cache_hit:cache_read/(cache_read+cache_write+input)"), "cache_hit")
    stat(by_id[6], inf("A", "usage", measures="messages", distinct="session"), "distinct_session")
    p = by_id[7]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="day", measures="cost,tokens", calc=TOK_M)]
    p["transformations"] = [organize({"cost": "Coste", "tokens_m": "Tokens"}, exclude=("day", "tokens")), to_time("time"), sort("time")]
    bars(by_id[8], inf("A", "usage", group="effort", measures="cost", sort="-cost"), "cost")
    bars(by_id[9], inf("A", "usage", group="project", measures="cost", sort="-cost"), "cost")

    # ------------------------------------------------------------------ Reparto del gasto
    p = by_id[11]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="model", measures="cost,tokens", top="model:10:cost", other="otros",
                                              calc="cost_share:cost/total_cost;tokens_share:tokens/total_tokens", sort="-cost")]
    p["transformations"] = [organize({"model": "Modelo", "cost_share": "Cuota del coste", "tokens_share": "Cuota de tokens"},
                                     exclude=("cost", "tokens")), sort("Cuota del coste", True)]
    p = by_id[12]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="model,effort", measures="cost", sort="-cost")]
    p["transformations"] = [organize({"model": "Modelo", "effort": "Effort", "cost": "Coste (USD)"}), sort("Coste (USD)", True)]

    # ------------------------------------------------------------------ Sesiones, skills y prompts
    p = by_id[15]
    p["datasource"], p["targets"] = INF, [inf("A", "skills", group="skill", measures="as_command,as_skill")]
    p["transformations"] = [organize({"skill": "Nombre", "as_command": "Como comando", "as_skill": "Como skill"},
                                     index={"skill": 0, "as_command": 1, "as_skill": 2}), sort("Como comando", True)]
    p = by_id[16]
    p["datasource"], p["targets"] = INF, [inf("A", "commands", group="command,model,origin", measures="cost")]
    org = p["transformations"][0]["options"]
    org["renameByName"] = {"command": "Comando", "model": "Modelo", "origin": "Origen", "cost": "Coste"}
    org["indexByName"] = {"command": 0, "model": 1, "origin": 2, "cost": 3}

    # ------------------------------------------------------------------ Mejoras
    stat(by_id[104], inf("A", "tools", measures="calls,avoidable_errors", calc="rate:avoidable_errors/calls"), "rate")
    p = by_id[105]
    p["datasource"], p["targets"] = INF, [inf("A", "compactions", measures="compactions"), inf("B", "interrupts", measures="interrupts")]
    p["fieldConfig"]["overrides"] += [display("compactions", "Compactaciones"), display("interrupts", "Interrupciones")]
    p = by_id[107]
    p["datasource"], p["targets"] = INF, [inf("A", "tools", group="tool,model", measures="calls,avoidable_errors",
                                              calc="rate:avoidable_errors/calls", nonzero="avoidable_errors", sort="-avoidable_errors")]
    p["transformations"] = [organize({"tool": "Herramienta", "model": "Modelo", "calls": "Llamadas", "avoidable_errors": "Errores", "rate": "Tasa"}),
                            sort("Errores", True)]
    p = by_id[108]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="week,model", measures="cost,messages",
                                              calc="cost_per_message:cost/messages", nonzero="cost_per_message")]
    p["transformations"][0]["options"]["valueField"] = "cost_per_message"
    p = by_id[109]
    p["datasource"], p["targets"] = INF, [inf("A", "tools", group="week,tool", measures="avoidable_errors,calls", top="tool:5:avoidable_errors",
                                              calc="rate:avoidable_errors/calls")]
    p["transformations"][0]["options"]["valueField"] = "rate"

    # ------------------------------------------------------------------ Diagnóstico del coste (new row, at the end)
    y = max(p["gridPos"]["y"] + p["gridPos"]["h"] for p in by_id.values())
    nid = max(by_id) + 1
    diag = [
        {"id": nid, "type": "row", "title": "Diagnóstico del coste", "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []},
        {"id": nid + 1, "type": "stat", "title": "Origen del coste", "gridPos": {"x": 0, "y": y + 1, "w": 10, "h": 5},
         "description": "De dónde sale el coste de los paneles: lo que informó la telemetría de Claude Code, lo calculado con la "
                        "tabla de precios (collectors/claude/prices.json) cuando no hubo telemetría (pila parada, telemetría "
                        "desactivada o sesiones anteriores), y los mensajes de modelos sin precio, que no suman coste.",
         "datasource": INF,
         "targets": [inf("A", "usage", group="cost_source", measures="cost,messages")],
         "transformations": [{"id": "rowsToFields", "options": {"mappings": [{"fieldName": "cost_source", "handlerKey": "field.name"},
                                                                          {"fieldName": "cost", "handlerKey": "field.value"}]}}],
         "fieldConfig": {"defaults": {"unit": "currencyUSD", "decimals": 2},
                         "overrides": [display("telemetry", "Telemetría"), display("computed", "Calculado con precios"),
                                       display("missing", "Sin precio")]},
         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "none",
                     "graphMode": "none", "textMode": "value_and_name"}},
        {"id": nid + 2, "type": "stat", "title": "Contadores OTel frente al registro", "gridPos": {"x": 10, "y": y + 1, "w": 14, "h": 5},
         "description": "Mientras dura la migración (ADR 0002): el coste de los contadores de OpenTelemetry que usaba el dashboard y el "
                        "del registro para las mismas peticiones (las que informó la telemetría). Deberían coincidir; los contadores "
                        "pierden sesiones cuyas series caducaron, y no filtran por proyecto.",
         "datasource": MIXED,
         "targets": [dict(refId="A", datasource=PROM, expr=otel_cost, instant=True, range=False, legendFormat="Contadores OTel"),
                     inf("B", "usage", measures="cost_telemetry", **{"f__cost_source": "telemetry"})],
         "fieldConfig": {"defaults": {"unit": "currencyUSD", "decimals": 2}, "overrides": [display("cost_telemetry", "Registro (telemetría)")]},
         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "none",
                     "graphMode": "none", "textMode": "value_and_name"}},
        {"id": nid + 3, "type": "table", "title": "Tabla de precios frente a la telemetría, por modelo", "gridPos": {"x": 0, "y": y + 6, "w": 24, "h": 8},
         "description": "Solo peticiones que la telemetría informó: su coste según Claude Code y el que da la tabla de precios. Una "
                        "desviación grande indica que la tabla está desactualizada para ese modelo; el coste calculado de las peticiones "
                        "sin telemetría hereda esa desviación.",
         "datasource": INF,
         "targets": [inf("A", "usage", group="model", measures="messages,cost_telemetry,cost_computed",
                         calc="deviation:cost_computed/cost_telemetry-1", sort="-cost_telemetry", **{"f__cost_source": "telemetry"})],
         "transformations": [organize({"model": "Modelo", "messages": "Peticiones", "cost_telemetry": "Telemetría",
                                       "cost_computed": "Tabla de precios", "deviation": "Desviación"})],
         "fieldConfig": {"defaults": {"unit": "currencyUSD", "decimals": 4},
                         "overrides": [{"matcher": {"id": "byName", "options": "Peticiones"}, "properties": [{"id": "unit", "value": "short"}, {"id": "decimals", "value": 0}]},
                                       {"matcher": {"id": "byName", "options": "Desviación"}, "properties": [
                                           {"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 1},
                                           {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                           {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                               {"color": "red", "value": None}, {"color": "orange", "value": -0.05}, {"color": "green", "value": -0.02},
                                               {"color": "orange", "value": 0.02}, {"color": "red", "value": 0.05}]}}]}]},
         "options": {"showHeader": True, "footer": {"show": False}}},
    ]
    d["panels"] += diag

    for v in d["templating"]["list"]:
        if v["name"] == "sessions":
            v["allValue"] = ".*"   # so ${sessions:queryparam} sends one value, not every session id
    d["description"] = (d.get("description") or "") + (" El coste viene del registro por petición del colector (ADR 0002): "
                                                        "el de la telemetría cuando existe y, si no, la tabla de precios.")
    return d


def main():
    with open(PATH, encoding="utf-8") as f:
        d = json.load(f)
    if any(p.get("title") == "Diagnóstico del coste" for p in d["panels"]):
        sys.exit("El dashboard ya está migrado.")
    d = migrate(d)
    text = json.dumps(d)
    left = [m for m in ("claude_day_", "claude_coach_day_", "claude_coach_week_") if m in text]
    if left:
        sys.exit("Quedan referencias antiguas: %s" % left)
    d["version"] = d.get("version", 1) + 1
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    print("Migrado:", PATH)


if __name__ == "__main__":
    main()

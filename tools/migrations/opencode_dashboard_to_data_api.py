"""ADR 0002: move the OpenCode dashboard from the per-day Prometheus series to the collector's /data API.

Run once from the repository root; it rewrites grafana/dashboards/opencode/opencode.json in place and
refuses to run twice. What changes in each panel is only where the numbers come from (targets and the
transformations that rename them); titles, layout, units, colours and overrides stay as they were.

- Panels read /data/<dataset> through the Infinity datasource with Grafana's time range.
- The Periodo/Desde/Hasta variables are replaced by Grafana's own time picker.
- The project variable reads a series that stays in Prometheus (opencode_cost_usd_total).
- Context and quota keep reading Prometheus: they are current state, not history.
"""
import json
import os
import sys
import urllib.parse

PATH = os.path.join("grafana", "dashboards", "opencode", "opencode.json")
BASE = "http://opencode-collector:9101/data/"
INF = {"type": "yesoreyeram-infinity-datasource", "uid": "coach-opencode"}
PROM = {"type": "prometheus", "uid": "prometheus"}
MIXED = {"type": "datasource", "uid": "-- Mixed --"}
RANGE = "from=${__from}&to=${__to}&${project:queryparam}"


def url(dataset, **params):
    """A /data URL; values are URL-encoded (a "+" in a calc would otherwise arrive as a space)."""
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


TOK_M = "tokens_m:tokens/1000000"


def migrate(d):
    by_id = {}

    def walk(p):
        by_id[p["id"]] = p
        for c in p.get("panels", []):
            walk(c)
    for p in d["panels"]:
        walk(p)

    # ------------------------------------------------------------------ resumen
    stat(by_id[1], inf("A", "usage", measures="cost"), "cost")
    stat(by_id[2], inf("A", "usage", measures="tokens", calc=TOK_M), "tokens_m")
    stat(by_id[3], inf("A", "usage", measures="cost,tokens", calc="usd_mtok:cost/(tokens/1000000)"), "usd_mtok")
    stat(by_id[4], inf("A", "usage", measures="input,cache_read,cache_write",
                       calc="cache_hit:cache_read/(cache_read+cache_write+input)"), "cache_hit")
    stat(by_id[5], inf("A", "sessions", measures="sessions"), "sessions")

    # Cuota y uso por proveedor: usage from /data, quota from Prometheus (current state)
    p = by_id[16]
    p["datasource"] = MIXED
    for t in p["targets"]:
        t["datasource"] = PROM
    p["targets"] = [inf("U", "usage", group="provider", measures="cost,messages,tokens", calc=TOK_M)] + \
        [t for t in p["targets"] if t["refId"] not in ("A", "B", "C")]
    tr = p["transformations"]
    tr[1]["options"]["include"]["pattern"] = "^(provider|message|cost|messages|tokens_m|Value #[D-I])$"
    org = tr[2]["options"]
    for old, new in (("Value #A", "cost"), ("Value #B", "messages"), ("Value #C", "tokens_m")):
        org["indexByName"][new] = org["indexByName"].pop(old)
        org["renameByName"][new] = org["renameByName"].pop(old)

    # Evolución semanal (the panel keeps its 14-week time override)
    p = by_id[6]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="week", measures="cost,tokens", calc=TOK_M)]
    p["transformations"] = [organize({"time": "Semana", "cost": "Coste", "tokens_m": "Tokens"}, exclude=("week", "tokens")),
                            to_time("Semana"), sort("Semana")]

    bars(by_id[7], inf("A", "usage", group="agent", measures="cost", sort="-cost"), "cost")
    bars(by_id[8], inf("A", "usage", group="project", measures="cost", sort="-cost"), "cost")

    # Cuota de coste y de tokens por modelo: the 10 most expensive models and the rest as "otros"
    p = by_id[9]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="model", measures="cost,tokens", top="model:10:cost", other="otros",
                                              calc="cost_share:cost/total_cost;tokens_share:tokens/total_tokens", sort="-cost")]
    p["transformations"] = [organize({"model": "Modelo", "cost_share": "Cuota del coste", "tokens_share": "Cuota de tokens"},
                                     exclude=("cost", "tokens")), sort("Cuota del coste", True)]

    # Detalle por modelo
    p = by_id[10]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="provider,model", measures="cost,messages,tokens", sort="-cost",
                                              calc=TOK_M + ";usd_mtok:cost/(tokens/1000000);cost_share:cost/total_cost")]
    p["transformations"] = [organize({"model": "Modelo", "provider": "Proveedor", "cost": "Coste", "messages": "Mensajes",
                                      "tokens_m": "Tokens (M)", "usd_mtok": "USD por M tokens", "cost_share": "% del coste"},
                                     exclude=("tokens",),
                                     index={"model": 0, "provider": 1, "messages": 2, "tokens_m": 3, "cost": 4, "cost_share": 5, "usd_mtok": 6}),
                            sort("Coste", True)]
    p["options"]["footer"]["fields"] = ["cost", "messages", "tokens_m", "cost_share"]

    # Comandos y Skills: same nested tables, numbers from the skills dataset
    for pid, kind, with_errors in ((11, "command", False), (17, "skill", True)):
        p = by_id[pid]
        p["datasource"] = INF
        p["targets"] = [inf("A", "skills", group="skill,model,agent", measures="cost,ok,failed", **{"f__kind": kind})]
        org = p["transformations"][1]["options"]
        org["renameByName"] = {"skill": "Nombre", "model": "Modelo", "agent": "Agente", "cost": "Coste", "ok": "Activaciones"}
        org["excludeByName"] = {"Time": True, "kind": True}
        if with_errors:
            org["renameByName"]["failed"] = "Errores"
        else:
            org["excludeByName"]["failed"] = True

    # Actividad diaria por modelo (days in the collector's time zone)
    p = by_id[13]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="day,model", measures="cost", top="model:8:cost", other="otros")]
    p["transformations"][0]["options"]["valueField"] = "cost"
    p = by_id[12]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="day,provider,model", measures="messages,tokens,cost", calc=TOK_M)]
    p["transformations"] = [organize({"day": "Día", "provider": "Proveedor", "model": "Modelo", "messages": "Mensajes",
                                      "tokens_m": "Tokens (M)", "cost": "Coste"}, exclude=("time", "tokens"),
                                     index={"day": 0, "model": 1, "provider": 2, "messages": 3, "tokens_m": 4, "cost": 5}),
                            sort("Día", True)]
    p["description"] = p.get("description", "").replace("Los días se cuentan en UTC.", "Los días se cuentan en la zona horaria del colector (TZ, por defecto Europe/Madrid).")

    # ------------------------------------------------------------------ Mejoras
    stat(by_id[23], inf("A", "tools", measures="calls,avoidable_errors", calc="rate:avoidable_errors/calls"), "rate")
    p = by_id[24]
    p["datasource"], p["targets"] = INF, [inf("A", "compactions", measures="compactions"), inf("B", "usage", measures="aborted")]
    p["fieldConfig"]["overrides"] += [
        {"matcher": {"id": "byName", "options": "compactions"}, "properties": [{"id": "displayName", "value": "Compactaciones"}]},
        {"matcher": {"id": "byName", "options": "aborted"}, "properties": [{"id": "displayName", "value": "Interrupciones"}]}]
    p = by_id[26]
    p["datasource"], p["targets"] = INF, [inf("A", "tools", group="tool,model", measures="calls,avoidable_errors",
                                              calc="rate:avoidable_errors/calls", nonzero="avoidable_errors", sort="-avoidable_errors")]
    p["transformations"] = [organize({"tool": "Herramienta", "model": "Modelo", "calls": "Llamadas", "avoidable_errors": "Errores", "rate": "Tasa"}),
                            sort("Errores", True)]
    p = by_id[27]
    p["datasource"], p["targets"] = INF, [inf("A", "usage", group="week,agent", measures="cost,messages", calc="cost_per_message:cost/messages")]
    p["transformations"][0]["options"]["valueField"] = "cost_per_message"
    p = by_id[28]
    p["datasource"], p["targets"] = INF, [inf("A", "tools", group="week,tool", measures="avoidable_errors,calls", top="tool:5:avoidable_errors",
                                              calc="rate:avoidable_errors/calls")]
    p["transformations"][0]["options"]["valueField"] = "rate"
    p = by_id[29]
    p["datasource"], p["targets"] = INF, [inf("A", "compactions", group="week", measures="compactions"),
                                          inf("B", "usage", group="week", measures="aborted")]
    p["transformations"] = [{"id": "merge", "options": {}},
                            organize({"week": "Semana", "compactions": "Compactaciones", "aborted": "Interrupciones"}, exclude=("time",)),
                            {"id": "convertFieldType", "options": {"conversions": [{"targetField": "Semana", "destinationType": "time", "dateFormat": "YYYY-MM-DD"}]}},
                            sort("Semana")]

    # ------------------------------------------------------------------ variables, time picker, links
    d["templating"]["list"] = [v for v in d["templating"]["list"] if v["name"] not in ("window", "desde", "hasta")]
    for v in d["templating"]["list"]:
        if v["name"] == "project":
            v["query"] = {"query": "label_values(opencode_cost_usd_total, project)", "refId": "project"}
            v["definition"] = "label_values(opencode_cost_usd_total, project)"
    d["timepicker"] = {"hidden": False}
    d["time"] = {"from": "now-90d", "to": "now"}
    d["description"] = ("Uso y coste de OpenCode a partir de su base de datos local. El selector de tiempo de Grafana y el "
                        "proyecto filtran los paneles; los días se cuentan en la zona horaria del colector. El coste es una "
                        "estimación de OpenCode, no una factura.")
    text = json.dumps(d, ensure_ascii=False)
    text = text.replace("window=${window}&from=${desde}&to=${hasta}", "from=${__from}&to=${__to}")
    return json.loads(text)


def main():
    with open(PATH, encoding="utf-8") as f:
        d = json.load(f)
    if not any(v["name"] == "window" for v in d["templating"]["list"]):
        sys.exit("El dashboard ya está migrado.")
    d = migrate(d)
    left = [m for m in ("opencode_day_", "opencode_weekly_", "$window", "$desde", "$hasta") if m in json.dumps(d)]
    if left:
        sys.exit("Quedan referencias antiguas: %s" % left)
    d["version"] = d.get("version", 1) + 1
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    print("Migrado:", PATH)


if __name__ == "__main__":
    main()

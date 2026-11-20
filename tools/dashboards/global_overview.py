"""Builds grafana/dashboards/global/ia-overview.json: spend across both tools, from the /data APIs (ADR 0002).

    python tools/dashboards/global_overview.py

The dashboard is generated: edit this script, not the JSON. Each panel asks both collectors and
merges the answers, so it has the whole history of both tools, in the collectors' time zone.
"""
import json
import os
import urllib.parse

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "grafana", "dashboards", "global", "ia-overview.json")
TOOLS = (("A", "Claude Code", "http://claude-collector:9100/data/", "coach-claude", "#D97757"),
         ("B", "OpenCode", "http://opencode-collector:9101/data/", "coach-opencode", "#5794F2"))
MIXED = {"type": "datasource", "uid": "-- Mixed --"}
TOK_M = "tokens_m:tokens/1000000"


def target(ref, base, uid, dataset, **params):
    q = "&".join("%s=%s" % (k.replace("__", "."), urllib.parse.quote(str(v), safe=":,/()*-_.")) for k, v in params.items())
    return {"refId": ref, "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": uid}, "type": "json", "source": "url",
            "format": "table", "parser": "backend", "url": base + dataset + "?from=${__from}&to=${__to}" + ("&" + q if q else ""),
            "url_options": {"method": "GET", "data": ""}, "root_selector": "", "columns": []}


def both(dataset, **params):
    return [target(ref, base, uid, dataset, **params) for ref, _n, base, uid, _c in TOOLS]


def per_tool_names():
    """Each frame is named after its tool, with the tool's colour.

    Grafana renames before it filters: a panel using these overrides must not pick its fields by name
    (reduceOptions.fields), or nothing matches. Ask the API for the one measure instead (measures=).
    """
    return [{"matcher": {"id": "byFrameRefID", "options": ref},
             "properties": [{"id": "displayName", "value": name}, {"id": "color", "value": {"mode": "fixed", "fixedColor": colour}}]}
            for ref, name, _b, _u, colour in TOOLS]


_ids = iter(range(1, 100))


def panel(title, typ, targets, grid, unit="currencyUSD", desc="", decimals=2, **kw):
    p = {"id": next(_ids), "title": title, "type": typ, "datasource": MIXED, "description": desc, "gridPos": grid,
         "targets": targets, "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals}, "overrides": []}, "options": {}}
    p.update(kw)
    return p


STAT = {"reduceOptions": {"calcs": ["sum"], "fields": "", "values": False}, "colorMode": "none", "graphMode": "none", "textMode": "value"}


def total(title, dataset, field, x, unit="currencyUSD", desc="", **params):
    """One number: the field summed over both tools (merge stacks the two one-row answers)."""
    return panel(title, "stat", both(dataset, **params), {"x": x, "y": 1, "w": 6, "h": 4}, unit=unit, desc=desc,
                 transformations=[{"id": "merge", "options": {}}],
                 options=dict(STAT, reduceOptions={"calcs": ["sum"], "fields": "/^%s$/" % field, "values": False}))


def build():
    panels = [{"id": 100, "type": "row", "title": "Gasto total en asistentes de código", "collapsed": False,
               "gridPos": {"x": 0, "y": 0, "w": 24, "h": 1}, "panels": []}]
    panels.append(total("Coste total", "usage", "cost", 0, desc="Coste estimado de Claude Code y OpenCode en el periodo elegido. "
                        "Es una estimación, no una factura: en planes de suscripción no es lo que pagas.", measures="cost"))
    panels.append(total("Tokens totales", "usage", "tokens_m", 6, unit="suffix: M", desc="Millones de tokens de ambas herramientas, caché incluida.",
                        measures="tokens", calc=TOK_M))
    panels.append(total("Sesiones", "sessions", "sessions", 12, unit="short", desc="Sesiones principales iniciadas en el periodo (sin subagentes).",
                        measures="sessions"))
    panels[-1]["fieldConfig"]["defaults"]["decimals"] = 0
    p = panel("Coste por herramienta", "stat", both("usage", measures="cost"), {"x": 18, "y": 1, "w": 6, "h": 4},
              desc="El coste de cada herramienta. Si solo instalaste una, la otra muestra un aviso de conexión.",
              options=dict(STAT, textMode="value_and_name", reduceOptions={"calcs": ["sum"], "fields": "", "values": False}))
    p["fieldConfig"]["overrides"] = per_tool_names()
    p["links"] = [{"title": "Dashboard de Claude Code", "url": "/d/claude-code?${__url_time_range}"},
                  {"title": "Dashboard de OpenCode", "url": "/d/opencode-usage?${__url_time_range}"}]
    panels.append(p)

    p = panel("Coste diario por herramienta", "timeseries", both("usage", group="day", measures="cost"), {"x": 0, "y": 5, "w": 16, "h": 9},
              desc="Coste de cada día por herramienta, con todo el historial de ambas. Los días se cuentan en la zona horaria "
                   "de los colectores (TZ, por defecto Europe/Madrid).",
              transformations=[{"id": "organize", "options": {"excludeByName": {"day": True}}},
                               {"id": "convertFieldType", "options": {"conversions": [{"targetField": "time", "destinationType": "time"}]}}],
              options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}})
    p["fieldConfig"]["defaults"]["custom"] = {"drawStyle": "bars", "fillOpacity": 80, "stacking": {"mode": "normal", "group": "A"},
                                              "barAlignment": -1, "lineWidth": 1}
    p["fieldConfig"]["overrides"] = per_tool_names()
    panels.append(p)

    p = panel("Reparto del coste", "piechart", both("usage", measures="cost"), {"x": 16, "y": 5, "w": 8, "h": 9},
              options={"reduceOptions": {"calcs": ["sum"], "fields": "", "values": False}, "pieType": "donut",
                       "legend": {"displayMode": "table", "placement": "bottom", "values": ["value", "percent"]}})
    p["fieldConfig"]["overrides"] = per_tool_names()
    panels.append(p)

    p = panel("Coste por proyecto (ambas herramientas)", "bargauge", both("usage", group="project", measures="cost"), {"x": 0, "y": 14, "w": 12, "h": 9},
              desc="Cuánto ha costado cada proyecto sumando las dos herramientas. El proyecto es la carpeta de trabajo de la sesión.",
              transformations=[{"id": "merge", "options": {}},
                               {"id": "groupBy", "options": {"fields": {"project": {"operation": "groupby"},
                                                                         "cost": {"operation": "aggregate", "aggregations": ["sum"]}}}},
                               {"id": "sortBy", "options": {"sort": [{"field": "cost (sum)", "desc": True}]}},
                               {"id": "limit", "options": {"limitField": 15}}],
              options={"reduceOptions": {"values": True, "calcs": [], "fields": "/^cost \\(sum\\)$/"}, "displayMode": "basic",
                       "orientation": "horizontal", "showUnfilled": True})
    panels.append(p)

    p = panel("Eficiencia por herramienta", "table",
              both("usage", group="tool", measures="cost,tokens,messages,input,cache_read,cache_write",
                   calc="usd_mtok:cost/(tokens/1000000);cost_per_message:cost/messages;cache_hit:cache_read/(cache_read+cache_write+input)"),
              {"x": 12, "y": 14, "w": 12, "h": 9},
              desc="USD por millón de tokens, coste medio por respuesta y acierto de caché de cada herramienta, para compararlas.",
              transformations=[{"id": "merge", "options": {}},
                               {"id": "organize", "options": {"excludeByName": {"tokens": True, "input": True, "cache_read": True, "cache_write": True},
                                                              "renameByName": {"tool": "Herramienta", "cost": "Coste", "messages": "Respuestas", "usd_mtok": "USD por M tokens",
                                                                               "cost_per_message": "Coste por respuesta", "cache_hit": "Acierto de caché"}}}],
              options={"showHeader": True, "footer": {"show": False}})
    p["fieldConfig"]["overrides"] = [
        {"matcher": {"id": "byName", "options": "Respuestas"}, "properties": [{"id": "unit", "value": "short"}, {"id": "decimals", "value": 0}]},
        {"matcher": {"id": "byName", "options": "Coste por respuesta"}, "properties": [{"id": "decimals", "value": 4}]},
        {"matcher": {"id": "byName", "options": "Acierto de caché"}, "properties": [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 1}]}]
    panels.append(p)

    panels.append({"id": 200, "type": "text", "title": "", "gridPos": {"x": 0, "y": 23, "w": 24, "h": 3},
                   "options": {"mode": "markdown", "content":
                               "El detalle está en el dashboard de cada herramienta: **[Claude Code](/d/claude-code)** (prompts, herramientas, "
                               "effort, diagnóstico del coste) y **[OpenCode](/d/opencode-usage)** (agentes, cuotas, evolución semanal). "
                               "El coste de Claude Code es el de su telemetría cuando existe y, si no, el de la tabla de precios; el de "
                               "OpenCode es el que guarda OpenCode. Si solo instalaste una herramienta, los paneles de la otra muestran un "
                               "aviso de conexión."}})
    return {"uid": "ia-overview", "title": "Resumen IA - Uso y coste", "tags": ["ia-metrics"], "timezone": "browser",
            "schemaVersion": 41, "version": 2, "editable": False, "time": {"from": "now-30d", "to": "now"}, "refresh": "5m",
            "description": "Gasto en asistentes de código: Claude Code y OpenCode juntos. Generado por tools/dashboards/global_overview.py.",
            "panels": panels, "templating": {"list": []},
            "links": [{"title": "Claude Code", "type": "link", "url": "/d/claude-code", "icon": "dashboard"},
                      {"title": "OpenCode", "type": "link", "url": "/d/opencode-usage", "icon": "dashboard"}]}


if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps(build(), ensure_ascii=False, indent=2) + "\n")
    print("Generado:", OUT)

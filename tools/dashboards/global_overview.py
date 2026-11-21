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


PROM = {"type": "prometheus", "uid": "prometheus"}


def prom(ref, expr, legend):
    return {"refId": ref, "datasource": PROM, "expr": expr, "instant": True, "range": False, "legendFormat": legend}


def counter(name):
    """A collector counter by name, with or without the _total suffix (it depends on the collector's version)."""
    return '{__name__=~"%s(_total)?"}' % name


def sources_row(y):
    """«Estado de las fuentes»: is each source up to date, is each service up, does the telemetry arrive."""
    row = {"id": 300, "type": "row", "title": "Estado de las fuentes", "collapsed": False,
           "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}
    stat = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "graphMode": "none",
            "textMode": "value_and_name", "justifyMode": "center", "orientation": "horizontal", "wideLayout": True,
            "text": {"titleSize": 13, "valueSize": 20}}
    last = panel("Última actividad registrada", "stat", [
        prom("A", "max(claude_index_last_message_timestamp_seconds > 0) * 1000", "Claude Code: conversaciones"),
        prom("B", "max(claude_telemetry_last_event_timestamp_seconds > 0) * 1000", "Claude Code: telemetría"),
        prom("C", "max(opencode_last_message_timestamp_seconds > 0) * 1000", "OpenCode")],
        {"x": 0, "y": y + 1, "w": 6, "h": 6}, unit="dateTimeFromNow", decimals=0, datasource=PROM,
        desc="Cuándo fue la última respuesta del modelo que ha visto cada fuente. Si acabas de usar la herramienta y aquí sale "
             "antiguo, sus datos no están llegando: mira «Retraso de lectura» y «Servicios». Con un periodo corto (15 minutos), "
             "un dashboard vacío con una actividad antigua aquí significa que no has usado la herramienta en ese tiempo.",
        options=dict(stat, colorMode="none"))
    last["fieldConfig"]["defaults"]["noValue"] = "sin datos"
    delay = panel("Retraso de lectura", "stat", [
        prom("A", "time() - max(claude_index_last_scan_timestamp_seconds > 0)", "Conversaciones de Claude Code"),
        prom("B", "time() - max(claude_telemetry_last_check_timestamp_seconds > 0)", "Telemetría (Loki)"),
        prom("C", "time() - max(opencode_db_read_timestamp_seconds > 0)", "opencode.db")],
        {"x": 6, "y": y + 1, "w": 6, "h": 6}, unit="s", decimals=0, datasource=PROM,
        desc="Hace cuánto que cada colector leyó su fuente con éxito. Lo normal: menos de un minuto para las conversaciones y "
             "Loki, y menos de tres para opencode.db. En rojo (más de una hora), el colector no puede leer: revisa "
             "docker compose logs claude-collector u opencode-collector.",
        options=dict(stat, colorMode="background"))
    delay["fieldConfig"]["defaults"].update(noValue="sin leer", thresholds={"mode": "absolute", "steps": [
        {"color": "green", "value": None}, {"color": "orange", "value": 600}, {"color": "red", "value": 3600}]},
        color={"mode": "thresholds"})
    up = panel("Servicios", "stat", [
        prom("A", 'up{job=~"claude-collector|otel-collector|loki|opencode"}', "{{job}}")],
        {"x": 12, "y": y + 1, "w": 6, "h": 6}, unit="none", decimals=0, datasource=PROM,
        desc="Si Prometheus llega a cada servicio. Los de una herramienta que no instalaste salen como caídos: "
             "claude-collector, otel-collector y loki son de Claude Code; opencode, de OpenCode.",
        options=dict(stat, colorMode="background"))
    up["fieldConfig"]["defaults"].update(color={"mode": "thresholds"}, thresholds={"mode": "absolute", "steps": [
        {"color": "red", "value": None}, {"color": "green", "value": 1}]},
        mappings=[{"type": "value", "options": {"0": {"text": "caído"}, "1": {"text": "en marcha"}}}])
    tel = panel("Telemetría de Claude Code en el periodo", "stat", [
        prom("A", "sum(increase(%s[$__range]))" % counter("otelcol_receiver_accepted_log_records"), "Eventos recibidos"),
        prom("B", "sum(increase(%s[$__range]))" % counter("otelcol_receiver_accepted_metric_points"), "Puntos de métricas recibidos"),
        prom("C", "sum(increase(%s[$__range])) or vector(0)" % counter("otelcol_receiver_refused_log_records|otelcol_exporter_send_failed_log_records"),
             "Rechazados o no guardados"),
        prom("D", "sum(increase(%s[$__range]))" % counter("loki_distributor_lines_received"), "Líneas guardadas en Loki")],
        {"x": 18, "y": y + 1, "w": 6, "h": 6}, unit="short", decimals=0, datasource=PROM,
        desc="Lo que ha recibido el OTel Collector de Claude Code en el periodo y lo que ha guardado Loki. «Rechazados o no "
             "guardados» por encima de 0 significa eventos perdidos (el coste se recalcula con la tabla de precios, pero se "
             "pierden el effort y las llamadas que no se escriben en la conversación). Los contadores empiezan de cero al "
             "reiniciar el servicio.",
        options=dict(stat, colorMode="value"))
    tel["fieldConfig"]["defaults"]["color"] = {"mode": "fixed", "fixedColor": "text"}
    tel["fieldConfig"]["overrides"] = [{"matcher": {"id": "byFrameRefID", "options": "C"}, "properties": [
        {"id": "color", "value": {"mode": "thresholds"}},
        {"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": 1}]}}]}]
    return [row, last, delay, up, tel]


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

    p = panel("Coste por herramienta en el tiempo", "timeseries", both("usage", group="auto", measures="cost"), {"x": 0, "y": 5, "w": 16, "h": 9},
              desc="Coste por herramienta a lo largo del periodo elegido, con todo el historial de ambas. El tamaño de cada barra se "
                   "adapta al periodo (de 1 minuto con «últimos 15 minutos» a semanas con varios meses), en la zona horaria de los "
                   "colectores (TZ, por defecto Europe/Madrid); pasa el ratón para ver el intervalo.",
              transformations=[{"id": "organize", "options": {"excludeByName": {"auto": True, "interval": True}}},
                               {"id": "convertFieldType", "options": {"conversions": [{"targetField": "time", "destinationType": "time"}]}}],
              options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}})
    p["fieldConfig"]["defaults"]["custom"] = {"drawStyle": "bars", "fillOpacity": 80, "stacking": {"mode": "normal", "group": "A"},
                                              "barAlignment": -1, "lineWidth": 1, "axisSoftMin": 0}
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
                               "Todo el coste es a precio de API (con suscripción no es lo que pagas): en Claude Code, el de su telemetría "
                               "o, si no, el de la tabla de precios; en OpenCode, el que guarda OpenCode o, si guardó 0, tokens × precio de "
                               "models.dev. Si solo instalaste una herramienta, los paneles de la otra muestran un aviso de conexión."}})
    panels.extend(sources_row(26))
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

"""HTML page with the detail of one OpenCode session. It only renders: the exporter reads the data."""
from common.html_page import (BASE_CSS as CSS, DATE_JS, LABELS, LIST_CSS, LIST_JS, PALETTE, PRICE_CSS,  # noqa: F401
                              duration, e, kilo, price_table, table, usd, when)


def context_card(d):
    last = d["last"]
    if not last:
        return '<div class="card sub">Esta sesión no tiene mensajes del asistente con tokens.</div>'
    parts = {"input": last["input"], "cache_read": last["cache_read"], "cache_write": last["cache_write"], "output": last["output"]}
    used = sum(parts.values())
    limit = d["limit"]
    if limit:
        pct = used / limit * 100
        head = '<b>%.0f %% usado</b><span class="sub">%s / %s · quedan %s</span>' % (pct, kilo(used), kilo(limit), kilo(max(limit - used, 0)))
        scale = max(limit, used)
    else:
        head = '<b>%s tokens</b><span class="sub">límite del modelo desconocido</span>' % kilo(used)
        scale = used or 1
    segs = "".join('<i style="width:%.2f%%;background:%s" title="%s: %s"></i>' % (v / scale * 100, PALETTE[k], LABELS[k], kilo(v)) for k, v in parts.items() if v)
    legend = "".join('<span><i style="background:%s"></i>%s %s</span>' % (PALETTE[k], LABELS[k], kilo(v)) for k, v in parts.items())
    return ('<div class="card"><div class="ctxhead">%s</div><div class="bar">%s</div><div class="legend">%s'
            '<span><i style="background:var(--free)"></i>Libre</span></div>'
            '<div class="sub" style="margin-top:8px;font-size:13px">Modelo: %s (%s). Contexto del último mensaje respondido.</div></div>'
            % (head, segs, legend, e(last["model"]), e(last["provider"])))


def line_chart(points, title, fmt, color, marks=(), hline=None):
    """points: list of y values, one per message. marks: indexes where a compaction happened."""
    if len(points) < 2:
        return '<div class="card sub">%s: hacen falta al menos dos mensajes.</div>' % e(title)
    w, h, left, right, top, bottom = 760, 200, 56, 12, 14, 26
    top_value = max(max(points), hline or 0) * 1.1 or 1
    n = len(points)

    def x(i):
        return left + (w - left - right) * i / (n - 1)

    def y(v):
        return top + (h - top - bottom) * (1 - v / top_value)

    grid = ""
    for k in range(5):
        v = top_value * k / 4
        grid += '<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="currentColor" opacity=".12"/><text x="%d" y="%.1f" text-anchor="end">%s</text>' % (
            left, w - right, y(v), y(v), left - 6, y(v) + 4, fmt(v))
    path = " ".join("%s%.1f,%.1f" % ("M" if i == 0 else "L", x(i), y(v)) for i, v in enumerate(points))
    marked = "".join('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" stroke="#E0B400" stroke-dasharray="3 3"/>' % (x(i), x(i), top, h - bottom) for i in marks if 0 <= i < n)
    limit_line = ""
    if hline:
        limit_line = '<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#E24D42" stroke-dasharray="5 4"/><text x="%d" y="%.1f" text-anchor="end">límite %s</text>' % (
            left, w - right, y(hline), y(hline), w - right, y(hline) - 4, fmt(hline))
    axis = '<text x="%d" y="%d">mensaje 1</text><text x="%d" y="%d" text-anchor="end">mensaje %d</text>' % (left, h - 8, w - right, h - 8, n)
    note = ' · las líneas amarillas son compactaciones' if marks else ''
    return ('<div class="card"><div class="sub" style="font-size:13px;margin-bottom:6px">%s%s</div><svg viewBox="0 0 %d %d" role="img" aria-label="%s">%s%s%s'
            '<path d="%s" fill="none" stroke="%s" stroke-width="2"/>%s</svg></div>'
            % (e(title), note, w, h, e(title), grid, limit_line, marked, path, color, axis))


def render(d, grafana_url):
    msgs = d["messages"]
    total_cost = sum(m["cost"] for m in msgs)
    total_tokens = sum(sum(m["tokens"].values()) for m in msgs)
    ctx_series = [sum(m["tokens"].values()) for m in msgs]
    cum, running = [], 0.0
    for m in msgs:
        running += m["cost"]
        cum.append(running)
    times = [m["t"] for m in msgs]
    marks = [sum(1 for t in times if t <= c) for c in d["compactions"]]

    by_model = {}
    for m in msgs:
        k = (m["model"], m["provider"], m["agent"])
        row = by_model.setdefault(k, [0, 0.0, 0])
        row[0] += 1
        row[1] += m["cost"]
        row[2] += sum(m["tokens"].values())
    model_rows = [[e(k[0]), e(k[1]), e(k[2]), str(v[0]), kilo(v[2]), usd(v[1])] for k, v in sorted(by_model.items(), key=lambda kv: -kv[1][1])]
    tool_rows = [[e(n), str(v[0]), str(v[1])] for n, v in sorted(d["tools"].items(), key=lambda kv: -kv[1][0])]
    skill_rows = [[e(n), "Comando" if k == "command" else "Skill", str(c)] for (k, n), c in sorted(d["skills"].items(), key=lambda kv: -kv[1])]
    child_rows = [['<a href="/session/%s">%s</a>' % (e(cid), e(title or cid)), usd(cost), when(upd)] for cid, title, cost, upd in d["children"]]

    span = (d["updated"] - d["created"]) if d["updated"] and d["created"] else 0
    meta = " · ".join(x for x in (e(d["project"]), "%d mensajes del asistente" % len(msgs), "duración %s" % duration(span)) if x)
    parent = ""
    if d["parent"]:
        parent = ' · <a href="/session/%s">sesión padre</a>' % e(d["parent"])
    diff = "+%d −%d en %d archivos" % (d["additions"], d["deletions"], d["files"]) if d["files"] else "sin cambios en archivos"

    parts = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>%s · Sesión de OpenCode</title><style>%s</style></head><body><div class='wrap'>" % (e(d["title"] or d["id"]), CSS),
        "<div class='sub'><a href='%s'>← Dashboard</a> · <a href='/sessions'>Todas las sesiones</a>%s</div>" % (e(grafana_url), parent),
        "<h1>%s</h1><div class='sub'>%s</div>" % (e(d["title"] or d["id"]), meta),
        "<div class='sub'>Creada %s · actualizada %s</div>" % (when(d["created"]), when(d["updated"])),
        "<div class='kpis'>",
        "<div class='kpi'><b>%s</b><span>Coste estimado</span></div>" % usd(total_cost),
        "<div class='kpi'><b>%s</b><span>Tokens</span></div>" % kilo(total_tokens),
        "<div class='kpi'><b>%s</b><span>Cambios</span></div>" % e(diff),
        "<div class='kpi'><b>%d</b><span>Herramientas llamadas</span></div>" % sum(v[0] for v in d["tools"].values()),
        "<div class='kpi'><b>%d</b><span>Compactaciones</span></div>" % len(d["compactions"]),
        "</div>",
        "<h2>Contexto</h2>", context_card(d),
        "<h2>Evolución</h2>",
        line_chart(ctx_series, "Tamaño del contexto en cada mensaje (tokens)", kilo, PALETTE["input"], marks, d["limit"] if d["limit"] and d["limit"] <= max(ctx_series or [1]) * 3 else None),
        "<div style='height:12px'></div>",
        line_chart(cum, "Coste acumulado (USD)", usd, PALETTE["output"]),
        "<h2>Modelos y agentes</h2>", table(["Modelo", "Proveedor", "Agente", "Mensajes", "Tokens", "Coste"], model_rows, numeric=(3, 4, 5)),
        "<h2>Skills y comandos</h2>", table(["Nombre", "Tipo", "Veces"], skill_rows, numeric=(2,)),
        "<h2>Herramientas</h2>", table(["Herramienta", "Llamadas", "Errores"], tool_rows, numeric=(1, 2)),
    ]
    if child_rows:
        parts += ["<h2>Sesiones hijas (subagentes)</h2>", table(["Sesión", "Coste", "Actualizada"], child_rows, numeric=(1,))]
    parts += [
        "<p class='note'>Datos de la base de datos de OpenCode, leídos en solo lectura. Aquí no aparece el texto de la conversación. "
        "El coste es una estimación de OpenCode, no una factura.</p>",
        "<script>document.querySelectorAll('time[data-ms]').forEach(function(t){t.textContent=new Date(+t.dataset.ms).toLocaleString()})</script>",
        "</div></body></html>",
    ]
    return "".join(parts)


def render_prices(rows, grafana_url, have_models):
    """Page /prices. rows: see exporter.model_costs."""
    def money(v):
        return "—" if v is None else "$%g" % v

    def state(r):
        n, zero, price, flagged, src = r[2], r[5], r[8], r[9], r[10]
        if flagged:
            return '<span class="tag bad">%s</span>' % ("SIN PRECIO" if zero == n else "parcial")
        if not zero:
            return '<span class="tag ok">OpenCode</span>'
        if src == "local":
            return '<span class="tag">local</span>'
        if not any((price.get(k) or 0) > 0 for k in ("input", "output")):
            return '<span class="tag">gratis</span>'
        return '<span class="tag ok">calculado</span>'

    body = []
    for r in rows:
        prov, model, n, tok, stored, zero, first, last, price, _f, src, api, pay = r
        p = price or {}
        body.append([e(prov), e(model), e(pay), state(r), str(n), kilo(tok), usd(stored), "<b>%s</b>" % usd(api)]
                    + [money(p.get(k)) if price else "—" for k in ("input", "output", "cache_read", "cache_write")]
                    + [e(src if src not in ("", "local") else ("—" if src == "local" else prov) if price else "—"), when(first), when(last)])
    flagged = {k for k, r in enumerate(rows) if r[9]}
    banner = ('<div class="card bad"><b>%d modelos sin precio</b> (resaltados en la tabla): OpenCode guardó coste 0 y no hay precio '
              'para ese modelo en el catálogo de models.dev, ni de su proveedor ni de su fabricante, así que su coste no cuenta en el dashboard. '
              'Puedes darle precio en la configuración de OpenCode (<code>provider.&lt;id&gt;.models.&lt;id&gt;.cost</code>); '
              'IA-metrics lo leerá de models.json cuando OpenCode lo actualice.</div>' % len(flagged)) if flagged else ""
    if not have_models:
        banner += '<div class="card sub">No se encuentra models.json (caché de OpenCode): no se pueden mostrar los precios.</div>'
    total_api, total_stored = sum(r[11] for r in rows), sum(r[4] for r in rows)
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Precios de los modelos de OpenCode</title><style>%s%s</style></head><body><div class='wrap'>"
            "<div class='sub'><a href='%s'>← Dashboard</a></div><h1>Precios de los modelos</h1>"
            "<div class='sub'>Coste equivalente de API de tus modelos de OpenCode: el que OpenCode guarda y, cuando guarda 0 (suscripción "
            "como Copilot, o un modelo que no conoce), tokens × precio de models.dev. Precios en USD por millón de tokens.</div>%s"
            "%s<p class='note'>Total: <b>%s</b> a precio de API, de los que OpenCode guardó %s. "
            "Estado: «OpenCode» si guardó el coste de todos los mensajes; «calculado» si alguno se valora con el precio de la tabla "
            "(«Precio de» dice de quién es: el propio proveedor, o el fabricante del modelo cuando el proveedor no da precio, como Copilot); "
            "«gratis» si models.dev lo da a 0; «local» para LM Studio, Ollama…; «SIN PRECIO» si no hay precio en ningún sitio. "
            "Pago: «suscripción» para los proveedores de OPENCODE_SUBSCRIPTION_PROVIDERS; en ellos el coste es lo que costaría por API, no lo que pagas.</p>"
            "<script>%s</script></div></body></html>"
            % (CSS, PRICE_CSS, e(grafana_url), banner,
               price_table(["Proveedor", "Modelo", "Pago", "Estado", "Mensajes", "Tokens", "Coste OpenCode", "Coste API",
                            "Entrada", "Salida", "Lect. caché", "Escr. caché", "Precio de", "Primer uso", "Último uso"],
                           body, numeric=range(4, 12), flagged=flagged),
               usd(total_api), usd(total_stored), DATE_JS))


def not_found(grafana_url):
    return ("<!doctype html><html lang='es'><meta charset='utf-8'><title>Sesión no encontrada</title><style>%s</style>"
            "<body><div class='wrap'><h1>Sesión no encontrada</h1><p class='sub'>OpenCode no tiene una sesión con ese identificador.</p>"
            "<a href='%s'>← Dashboard</a></div></body></html>" % (CSS, e(grafana_url)))


def render_list(rows, grafana_url, subagents, note, toggle_href):
    """rows: (id, title, parent, project, created, updated, messages, cost, tokens, agent)"""
    def cell(v, text):
        return '<td class="n" data-v="%s">%s</td>' % (e(v), text)

    body = []
    for sid, title, parent, project, created, updated, msgs, cost, tokens, agent in rows:
        tag = '<span class="tag">subagente</span>' if parent else ""
        body.append('<tr><td><a href="/session/%s">%s</a>%s</td><td>%s</td><td>%s</td>%s%s%s%s%s</tr>' % (
            e(sid), e(title or sid), tag, e(project), e(agent or "—"), cell(msgs, str(msgs)), cell(tokens, kilo(tokens)),
            cell(cost, usd(cost)), cell(created, when(created)), cell(updated, when(updated))))
    heads = ["Sesión", "Proyecto", "Agente", "Mensajes", "Tokens", "Coste", "Creada", "Actualizada"]
    th = "".join('<th class="s%s">%s</th>' % (" n" if i >= 3 else "", h) for i, h in enumerate(heads))
    toggle = "<a href='%s'>%s</a>" % (e(toggle_href), "Ocultar subagentes" if subagents else "Incluir subagentes")
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Sesiones de OpenCode</title><style>%s%s</style></head><body><div class='wrap'>"
            "<div class='sub'><a href='%s'>← Dashboard</a></div><h1>Sesiones</h1>"
            "<div class='sub'>%s</div>"
            "<div class='tools'><input id='q' type='search' placeholder='Filtrar por título, proyecto o agente' aria-label='Filtrar'>"
            "<span class='sub'><b id='cnt'>%d</b> de %d sesiones</span><span class='sub'>%s</span></div>"
            "<div class='card scroll'><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>"
            "<p class='note'>Pulsa una cabecera para ordenar. El coste es una estimación de OpenCode, no una factura. Aquí no aparece el texto de la conversación.</p>"
            "<script>%s</script></div></body></html>"
            % (CSS, LIST_CSS, e(grafana_url), e(note), len(rows), len(rows), toggle, th, "".join(body), LIST_JS))

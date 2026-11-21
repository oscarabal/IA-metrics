"""HTML pages for the sessions of Claude Code: a list and the detail of one session. They only render."""
from common.html_page import (BASE_CSS, DATE_JS, LABELS, LIST_CSS, LIST_JS, PALETTE, PRICE_CSS, TIME_JS,  # noqa: F401
                              duration, e, kilo, price_table, table, usd, when)

CSS = BASE_CSS + LIST_CSS.lstrip("\n")


def context_card(d):
    last = d["last"]
    if not last:
        return '<div class="card sub">Esta sesión no tiene mensajes del asistente con tokens.</div>'
    parts = {k: last[k] for k in ("input", "cache_read", "cache_write", "output")}
    used = sum(parts.values())
    limit = d["limit"]
    pct = used / limit * 100
    head = '<b>%.0f %% usado</b><span class="sub">%s / %s · quedan %s</span>' % (min(pct, 100), kilo(used), kilo(limit), kilo(max(limit - used, 0)))
    scale = max(limit, used)
    segs = "".join('<i style="width:%.2f%%;background:%s" title="%s: %s"></i>' % (v / scale * 100, PALETTE[k], LABELS[k], kilo(v)) for k, v in parts.items() if v)
    legend = "".join('<span><i style="background:%s"></i>%s %s</span>' % (PALETTE[k], LABELS[k], kilo(v)) for k, v in parts.items())
    return ('<div class="card"><div class="ctxhead">%s</div><div class="bar">%s</div><div class="legend">%s'
            '<span><i style="background:var(--free)"></i>Libre</span></div>'
            '<div class="sub" style="margin-top:8px;font-size:13px">Modelo: %s. Contexto del último mensaje del hilo principal. %s</div></div>'
            % (head, segs, legend, e(last["model"]), e(d["limit_note"])))


def line_chart(points, title, fmt, color, marks=(), note_marks=""):
    if len(points) < 2:
        return '<div class="card sub">%s: hacen falta al menos dos puntos.</div>' % e(title)
    w, h, left, right, top, bottom = 760, 200, 56, 12, 14, 26
    top_value = max(points) * 1.1 or 1
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
    axis = '<text x="%d" y="%d">mensaje 1</text><text x="%d" y="%d" text-anchor="end">mensaje %d</text>' % (left, h - 8, w - right, h - 8, n)
    note = (" · " + note_marks) if marks else ""
    return ('<div class="card"><div class="sub" style="font-size:13px;margin-bottom:6px">%s%s</div><svg viewBox="0 0 %d %d" role="img" aria-label="%s">%s%s'
            '<path d="%s" fill="none" stroke="%s" stroke-width="2"/>%s</svg></div>'
            % (e(title), e(note), w, h, e(title), grid, marked, path, color, axis))


def render_detail(d, dashboard_url):
    main = d["main"]
    ctx = [sum(m["tokens"].values()) for m in main]
    times = [m["t"] for m in main]
    marks = [sum(1 for t in times if t <= c[0]) for c in d["compactions"]]
    known = [m for m in main if m["cost"] is not None]
    cum, running = [], 0.0
    for m in main:
        running += m["cost"] or 0
        cum.append(running)
    cost_total = d["cost_known"]
    coverage = "%d de %d mensajes con coste" % (d["msgs_known"], d["msgs_total"])

    model_rows = [[e(m), str(v[0]), kilo(v[1]), usd(v[2]) if v[3] else "—"] for m, v in sorted(d["models"].items(), key=lambda kv: -kv[1][1])]
    tool_rows = [[e(n), str(v[0]), str(v[1])] for n, v in sorted(d["tools"].items(), key=lambda kv: -kv[1][0])]
    skill_rows = [[e(n), str(v[0]), str(v[1]), usd(d["attributed"][n]) if n in d["attributed"] else "—"]
                  for n, v in sorted(d["skills"].items(), key=lambda kv: -(kv[1][0] + kv[1][1]))]
    comp_rows = [[when(t), e(trigger or "—"), kilo(pre), kilo(post)] for t, pre, post, trigger in d["compactions"]]
    sub = d["sub"]
    sub_rows = [[str(sub["agents"]), str(sub["messages"]), kilo(sub["tokens"]), usd(sub["cost"]) if sub["cost"] else "—"]] if sub["agents"] else []

    span = (d["updated"] - d["created"]) if d["updated"] and d["created"] else 0
    meta = " · ".join(x for x in (e(d["project"]), e(d["branch"]) if d["branch"] else "", "%d mensajes del hilo principal" % len(main), "duración %s" % duration(span)) if x)
    parts = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>%s · Sesión de Claude Code</title><style>%s</style></head><body><div class='wrap'>" % (e(d["title"] or d["id"]), CSS),
        "<div class='sub'><a href='%s'>← Dashboard</a> · <a href='/sessions'>Todas las sesiones</a></div>" % e(dashboard_url),
        "<h1>%s</h1><div class='sub'>%s</div>" % (e(d["title"] or d["id"]), meta),
        "<div class='sub'>Creada %s · actualizada %s</div>" % (when(d["created"]), when(d["updated"])),
        "<div class='kpis'>",
        "<div class='kpi'><b>%s</b><span>Coste conocido (%s)</span></div>" % (usd(cost_total) if d["msgs_known"] else "—", e(coverage)),
        "<div class='kpi'><b>%s</b><span>Tokens (con subagentes)</span></div>" % kilo(d["tokens_total"]),
        "<div class='kpi'><b>%d</b><span>Herramientas llamadas</span></div>" % sum(v[0] for v in d["tools"].values()),
        "<div class='kpi'><b>%d</b><span>Compactaciones</span></div>" % len(d["compactions"]),
        "<div class='kpi'><b>%d</b><span>Subagentes</span></div>" % sub["agents"],
        "</div>",
        "<h2>Contexto</h2>", context_card(d),
        "<h2>Evolución</h2>",
        line_chart(ctx, "Tamaño del contexto en cada mensaje del hilo principal (tokens)", kilo, PALETTE["input"], marks, "las líneas amarillas son compactaciones"),
    ]
    if len(known) >= 2:
        parts += ["<div style='height:12px'></div>", line_chart(cum, "Coste conocido acumulado (USD)", usd, PALETTE["output"])]
    parts += ["<h2>Modelos</h2>", table(["Modelo", "Mensajes", "Tokens", "Coste conocido"], model_rows, numeric=(1, 2, 3)),
              "<h2>Skills y comandos</h2>", table(["Nombre", "Como comando", "Como skill", "Coste atribuido"], skill_rows, numeric=(1, 2, 3)),
              "<h2>Herramientas</h2>", table(["Herramienta", "Llamadas", "Errores"], tool_rows, numeric=(1, 2))]
    if comp_rows:
        parts += ["<h2>Compactaciones</h2>", table(["Cuándo", "Disparo", "Tokens antes", "Tokens después"], comp_rows, numeric=(2, 3))]
    if sub_rows:
        parts += ["<h2>Subagentes</h2>", table(["Subagentes", "Mensajes", "Tokens", "Coste conocido"], sub_rows, numeric=(0, 1, 2, 3))]
    parts += [
        "<p class='note'>Datos de los ficheros de conversación de Claude Code, leídos en solo lectura. Aquí no aparece el texto de la conversación. "
        "El coste sale de la telemetría y solo existe para las llamadas registradas desde que se activó; el resto muestra «—». "
        "El título lo pone Claude Code a partir de la conversación.</p>",
        "<script>%s</script></div></body></html>" % TIME_JS,
    ]
    return "".join(parts)


def render_list(rows, dashboard_url, note, toggle_href=None):
    """rows: (id, title, project, model, messages, tokens, cost or None, created, updated, subagents)"""
    def cell(v, text):
        return '<td class="n" data-v="%s">%s</td>' % (e(v), text)

    body = []
    for sid, title, project, model, msgs, tokens, cost, created, updated, subs in rows:
        tag = '<span class="tag">%d subagentes</span>' % subs if subs else ""
        body.append('<tr><td><a href="/session/%s">%s</a>%s</td><td>%s</td><td>%s</td>%s%s%s%s%s</tr>' % (
            e(sid), e(title or sid[:8]), tag, e(project), e(model), cell(msgs, str(msgs)), cell(tokens, kilo(tokens)),
            cell(cost if cost is not None else -1, usd(cost) if cost is not None else "—"), cell(created, when(created)), cell(updated, when(updated))))
    heads = ["Sesión", "Proyecto", "Modelo", "Mensajes", "Tokens", "Coste conocido", "Creada", "Actualizada"]
    th = "".join('<th class="s%s">%s</th>' % (" n" if i >= 3 else "", h) for i, h in enumerate(heads))
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Sesiones de Claude Code</title><style>%s</style></head><body><div class='wrap'>"
            "<div class='sub'><a href='%s'>← Dashboard</a></div><h1>Sesiones</h1><div class='sub'>%s</div>"
            "<div class='tools'><input id='q' type='search' placeholder='Filtrar por título, proyecto o modelo' aria-label='Filtrar'>"
            "<span class='sub'><b id='cnt'>%d</b> de %d sesiones</span></div>"
            "<div class='card scroll'><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>"
            "<p class='note'>Pulsa una cabecera para ordenar. El coste sale de la telemetría y solo existe desde que se activó; «—» es una sesión sin coste conocido. "
            "Aquí no aparece el texto de la conversación.</p><script>%s</script></div></body></html>"
            % (CSS, e(dashboard_url), e(note), len(rows), len(rows), th, "".join(body), LIST_JS))


def render_prices(used, table_rows, source, dashboard_url, pending):
    """Page /prices.
    used: (model, messages, tokens, priced messages, cost, first ms, last ms, current period or None)
    table_rows: (model, period, number of periods) of every model in prices.json"""
    def money(v):
        return "—" if v is None else ("$%g" % v)

    def prices(p):
        return [money(p.get(k)) for k in ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")] if p else ["—"] * 5

    def state(msgs, priced):
        if priced == msgs:
            return '<span class="tag ok">sí</span>'
        return '<span class="tag bad">SIN PRECIO</span>' if not priced else '<span class="tag bad">parcial</span>'

    def source(p):
        return "—" if not p else ("models.dev" if p.get("source") == "models.dev" else "prices.json")

    mine = [[e(m), state(n, pr), str(n), kilo(tok), usd(cost)] + prices(p) + [source(p), when(first), when(last)]
            for m, n, tok, pr, cost, first, last, p in used]
    allp = [[e(m), e(p.get("from", "")) + (' <span class="sub">(%d periodos)</span>' % k if k > 1 else "")] + prices(p)
            + ["sí" if p.get("fast") else "", "×%g" % p["geo_us"] if p.get("geo_us") else "",
               "sí" if p.get("tiers") else ""] for m, p, k in table_rows]
    flagged = {k for k, (_m, n, _t, pr, *_r) in enumerate(used) if pr < n}
    banner = ('<div class="card bad"><b>%d modelos sin precio</b> (resaltados en la tabla): no están en prices.json ni en models.dev, '
              'así que su coste sin telemetría queda como «missing». '
              'Añádelos a <code>collectors/claude/prices.json</code> y ejecuta <code>docker compose restart claude-collector</code>.</div>'
              % len(flagged)) if flagged else ""
    if pending:
        banner = '<div class="card sub">%s</div>' % e(pending) + banner
    total = sum(c for *_x, c, _f, _l, _p in used)
    price_heads = ["Entrada", "Salida", "Escr. caché 5 min", "Escr. caché 1 h", "Lect. caché"]
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Precios de los modelos de Claude</title><style>%s%s</style></head><body><div class='wrap'>"
            "<div class='sub'><a href='%s'>← Dashboard</a></div><h1>Precios de los modelos</h1>"
            "<div class='sub'>Lo mismo que <code>python tools/check_claude_prices.py</code>, leído de tus conversaciones. "
            "Precios en USD por millón de tokens, vigentes hoy. Fuente: %s</div>%s"
            "<h2>Tus modelos</h2>%s<p class='note'>Coste estimado con la tabla de precios para todos los mensajes (aunque tengan coste de telemetría): "
            "%s en total. Sirve para comprobar la tabla; el dashboard usa el de la telemetría cuando existe.</p>"
            "<h2>Tabla de precios (prices.json)</h2>%s"
            "<p class='note'>«Desde» es la fecha del precio vigente; un cambio de precio se añade como un periodo nuevo, sin borrar el anterior. "
            "Los modelos se reconocen por prefijo, sin la fecha ni [1m]. Rápido: tiene precio de modo rápido. EE. UU.: multiplicador de inference_geo=us. "
            "Tramos: precio distinto según el tamaño del prompt. «Precio de»: prices.json o, para los modelos que no están en ella, la copia de "
            "models.dev que el colector descarga cada día (sin periodos, modo rápido ni recargo de EE. UU.; prices.json manda).</p><script>%s</script></div></body></html>"
            % (CSS, PRICE_CSS, e(dashboard_url), e(source), banner,
               price_table(["Modelo", "Precio", "Mensajes", "Tokens", "Coste estimado"] + price_heads + ["Precio de", "Primer uso", "Último uso"], mine,
                           numeric=(2, 3, 4, 5, 6, 7, 8, 9, 11, 12), flagged=flagged),   # «Precio de» (10) is text
               usd(total),
               price_table(["Modelo", "Desde"] + price_heads + ["Rápido", "EE. UU.", "Tramos"], allp, numeric=range(2, 7)),
               DATE_JS))


def not_found(dashboard_url):
    return ("<!doctype html><html lang='es'><meta charset='utf-8'><title>Sesión no encontrada</title><style>%s</style>"
            "<body><div class='wrap'><h1>Sesión no encontrada</h1><p class='sub'>Claude Code no tiene una sesión con ese identificador.</p>"
            "<a href='%s'>← Dashboard</a></div></body></html>" % (CSS, e(dashboard_url)))

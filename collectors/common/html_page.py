"""HTML pieces shared by the collectors' pages (sessions, report, prices): the base stylesheet, the
list and price-table styles, the small formatting helpers and the scripts that localise times.
Pages are server-rendered with inline CSS and no JS framework; every value goes through e()."""
import html

BASE_CSS = """
:root{--bg:#f6f6f3;--surface:#fff;--fg:#1d2127;--muted:#5d6672;--line:#dcdcd5;--free:#e4e4de;--accent:#5794F2}
@media (prefers-color-scheme:dark){:root{--bg:#14171b;--surface:#1c2025;--fg:#e8eaec;--muted:#9aa3ad;--line:#2d333a;--free:#2b3037}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif;padding:24px max(16px,env(safe-area-inset-left))}
.wrap{max-width:1000px;margin:0 auto}
a{color:var(--accent)}
h1{font-size:24px;margin:4px 0 6px;overflow-wrap:anywhere}
h2{font-size:15px;margin:28px 0 10px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.sub{color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:18px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.kpi b{display:block;font-size:22px}
.kpi span{color:var(--muted);font-size:13px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px 16px}
.ctxhead{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.bar{display:flex;height:16px;border-radius:4px;overflow:hidden;background:var(--free)}
.bar i{display:block;height:100%}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:13px;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--muted);font-weight:600;font-size:13px}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
svg{width:100%;height:auto;display:block}
svg text{fill:var(--muted);font-size:11px}
.note{color:var(--muted);font-size:13px;margin-top:28px}
"""

LIST_CSS = """
.tools{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:14px 0}
input[type=search]{padding:7px 10px;border:1px solid var(--line);border-radius:5px;background:var(--surface);color:var(--fg);min-width:240px;font:inherit}
th.s{cursor:pointer;user-select:none}
th.s:hover{color:var(--fg)}
td a{overflow-wrap:anywhere}
.tag{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:1px 7px;margin-left:6px}
"""

LABELS = {"input": "Entrada", "cache_read": "Caché leída", "cache_write": "Caché escrita", "output": "Salida"}

PALETTE = {"input": "#5794F2", "cache_read": "#8AB8FF", "cache_write": "#2EC4B6", "output": "#F2994A"}

LIST_JS = """
var q=document.getElementById('q'),tb=document.querySelector('tbody'),rows=[].slice.call(tb.rows),cnt=document.getElementById('cnt');
function filt(){var v=q.value.toLowerCase(),n=0;rows.forEach(function(r){var ok=r.textContent.toLowerCase().indexOf(v)>=0;r.style.display=ok?'':'none';if(ok)n++});cnt.textContent=n}
q.addEventListener('input',filt);
document.querySelectorAll('th.s').forEach(function(th,i){var asc=false;th.addEventListener('click',function(){asc=!asc;
 rows.sort(function(a,b){var x=a.cells[i].dataset.v||a.cells[i].textContent,y=b.cells[i].dataset.v||b.cells[i].textContent,nx=parseFloat(x),ny=parseFloat(y);
  var c=(!isNaN(nx)&&!isNaN(ny))?nx-ny:String(x).localeCompare(String(y));return asc?c:-c});
 rows.forEach(function(r){tb.appendChild(r)})})});
document.querySelectorAll('time[data-ms]').forEach(function(t){t.textContent=new Date(+t.dataset.ms).toLocaleString()});
"""

TIME_JS = "document.querySelectorAll('time[data-ms]').forEach(function(t){t.textContent=new Date(+t.dataset.ms).toLocaleString()})"

PRICE_CSS = """
:root{--ok-bg:#e3f4e8;--ok-fg:#1d6b35;--ok-line:#bfe3c9;--bad-bg:#fff4f2;--bad-fg:#a1261b;--bad-line:#e8a29b}
@media (prefers-color-scheme:dark){:root{--ok-bg:#15301f;--ok-fg:#7fd89c;--ok-line:#24553a;--bad-bg:#2b1917;--bad-fg:#ff9b8f;--bad-line:#6e3029}}
.wrap{max-width:1500px}
.prices table{font-size:13px}
.prices th,.prices td{white-space:nowrap;padding:6px 9px}
.prices th{vertical-align:bottom}
.prices tr.flag td{background:var(--bad-bg)}
.tag{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:1px 8px;margin-left:0;color:var(--muted)}
.tag.ok{background:var(--ok-bg);color:var(--ok-fg);border-color:var(--ok-line)}
.tag.bad{background:var(--bad-bg);color:var(--bad-fg);border-color:var(--bad-line)}
.card.bad{background:var(--bad-bg);border-color:var(--bad-line);color:var(--fg);margin:14px 0}
.card.bad b{color:var(--bad-fg)}
"""
DATE_JS = "document.querySelectorAll('time[data-ms]').forEach(function(t){t.textContent=new Date(+t.dataset.ms).toLocaleDateString()})"


def e(v):
    return html.escape(str(v), quote=True)


def kilo(n):
    n = float(n)
    if n >= 1_000_000:
        return ("%.2f" % (n / 1_000_000)).rstrip("0").rstrip(".") + "M"
    if n >= 1000:
        return "%.1fk" % (n / 1000)
    return "%d" % n


def usd(v):
    return "$%.2f" % v if v >= 0.01 or v == 0 else "$%.3f" % v


def when(ms):
    """A moment as a <time> element that the page script shows in the reader's time zone."""
    if not ms:
        return "—"
    return '<time data-ms="%d"></time>' % ms


def duration(ms):
    s = int(ms / 1000)
    if s < 60:
        return "%d s" % s
    if s < 3600:
        return "%d min" % (s // 60)
    if s < 86400:
        return "%d h %d min" % (s // 3600, (s % 3600) // 60)
    return "%d d %d h" % (s // 86400, (s % 86400) // 3600)


def table(headers, rows, numeric=()):
    if not rows:
        return '<div class="card sub">Sin datos.</div>'
    head = "".join('<th class="%s">%s</th>' % ("n" if i in numeric else "", e(hd)) for i, hd in enumerate(headers))
    body = "".join("<tr>%s</tr>" % "".join('<td class="%s">%s</td>' % ("n" if i in numeric else "", c) for i, c in enumerate(r)) for r in rows)
    return '<div class="card scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (head, body)


def price_table(headers, rows, numeric=(), flagged=()):
    """Like table(), with one line per row and the rows in `flagged` highlighted."""
    if not rows:
        return '<div class="card sub">Sin datos.</div>'
    head = "".join('<th class="%s">%s</th>' % ("n" if i in numeric else "", e(hd)) for i, hd in enumerate(headers))
    body = "".join('<tr%s>%s</tr>' % (' class="flag"' if k in flagged else "",
                   "".join('<td class="%s">%s</td>' % ("n" if i in numeric else "", c) for i, c in enumerate(r))) for k, r in enumerate(rows))
    return '<div class="card scroll prices"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (head, body)

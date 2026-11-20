"""Markdown helpers shared by the improvement reports of both collectors (numbers and tables)."""
import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def usd(v):
    return "—" if v is None else "%.2f $" % v if abs(v) >= 0.01 or v == 0 else "%.4f $" % v


def usd4(v):
    return "—" if v is None else "%.4f $" % v


def tok(v):
    return "%.1f M" % (v / 1e6) if v >= 1e6 else "%.0f k" % (v / 1e3) if v >= 1e3 else "%d" % v


def kb(v):
    return "%.0f kB" % (v / 1000) if v >= 1000 else "%d B" % v


def pct(v):
    return "%.1f %%" % (100 * v)


def _rate(a, b):
    return a / b if b else 0.0


def cell(v):
    """One table cell: a single line (names come from conversations and must not add rows or text) with | escaped."""
    return _CONTROL.sub(" ", str(v)).replace("|", "\\|")


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(cell(c) for c in r) + " |")
    return "\n".join(out)

"""What the improvement reports of both collectors share (ADR 0001, ADR 0004).

The rules D1–D10 exist in both collectors with the same meaning, but each one reads its own data
(Claude Code's conversations and telemetry, OpenCode's database) and words its advice for its tool, so
each collector keeps its own rule bodies in coach/report.py. What must not drift between them lives here:
the rule catalogue, every threshold of D1–D10, how a finding is shaped and how its severity is graded,
and the format version of the report. Change a threshold here and both reports change together.
"""
FORMAT_VERSION = 1

# Shared rules; D2 is named by each collector (cost by model and origin, or by agent)
SHARED_RULES = {
    "D1": "Errores de herramienta", "D2": None, "D3": "Bucles y exploración", "D4": "Contexto",
    "D5": "Permisos", "D6": "Caché", "D7": "Skills", "D8": "Modelo fijado en comandos", "D9": "Interrupciones",
    "D10": "Comandos sin uso",
}


def rules(d2_name, **own):
    """The rule catalogue of one collector: the shared rules, in order, then its own."""
    out = dict(SHARED_RULES, D2=d2_name)
    out.update(own)
    return out


# D1 tool errors: a tool/class is reported with this many avoidable errors, or with fewer if its rate is high
D1_MIN_ERRORS = 10
D1_MIN_ERRORS_HIGH_RATE = 5
D1_HIGH_RATE = 0.05
D1_ONE_MODEL_SHARE = 0.6        # «el N % de estos errores son de <modelo>» from this share
# D2 cost concentration: enough messages on both sides, a big share and twice the reference cost per message
D2_MIN_MESSAGES = 20
D2_MIN_SHARE = 0.4
D2_COST_RATIO = 2
D2_OUTSIDE_COMMANDS_SHARE = 0.7     # OpenCode: from this share of an agent's cost outside commands, the advice changes
# D3 loops, error streaks and long turns: reported from this many cases
D3_MIN_CASES = 3
# D4 context (OpenCode): a model is reported from this many context overflow errors
D4_MIN_OVERFLOW_ERRORS = 2
# D5 permissions: reported from this many denials or blocks
D5_MIN = 3
# D6 cache: a model with this many uncached input tokens and a hit rate below this
D6_MIN_UNCACHED_TOKENS = 5_000_000
D6_MAX_CACHE_HIT = 0.5
# D8 pinned model health: a tool fails at least this often for the model a command pins
D8_MIN_ERRORS = 5
D8_MIN_RATE = 0.10
D8_MIN_MESSAGE_ERRORS = 5           # OpenCode: or the model's own message errors, this many and this often
D8_MIN_MESSAGE_ERROR_RATE = 0.03
# D9 interruptions: an answer stopped and followed by a new message within this window counts as a quick
# retry; reported from this many
D9_QUICK_RETRY_MS = 120_000
D9_MIN_QUICK_RETRIES = 5
# D7 / D10 unused skills and commands: only with this much history, and from this many unused
UNUSED_MIN_DAYS = 30
D7_MIN_UNUSED = 2
D10_MIN_UNUSED = 3

# Severity of a finding, from its impact in dollars (share of the period's cost), tokens or count
SEVERITY_USD_HIGH = 0.10
SEVERITY_USD_MEDIUM = 0.02
SEVERITY_TOKENS_MEDIUM = 50_000_000
SEVERITY_COUNT_HIGH = 100
SEVERITY_COUNT_MEDIUM = 20


def pct(a, b):
    return a / b if b else 0.0


def quantile(values, q):
    if not values:
        return 0
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def severity(f, summary):
    cost = summary["cost_usd"]
    usd = f.get("impact_usd") or 0
    if cost > 0 and usd:
        share = usd / cost
        return "alta" if share >= SEVERITY_USD_HIGH else "media" if share >= SEVERITY_USD_MEDIUM else "baja"
    if f.get("impact_tokens"):
        return "media" if f["impact_tokens"] >= SEVERITY_TOKENS_MEDIUM else "baja"
    n = f.get("impact_count") or 0
    return "alta" if n >= SEVERITY_COUNT_HIGH else "media" if n >= SEVERITY_COUNT_MEDIUM else "baja"


def finding(detector, title, evidence, recommendation, impact_usd=None, impact_count=None, impact_tokens=None,
            sessions=(), subject=""):
    return {"detector": detector, "subject": subject, "title": title, "evidence": evidence,
            "recommendation": recommendation, "impact_usd": round(impact_usd, 4) if impact_usd is not None else None,
            "impact_count": impact_count, "impact_tokens": impact_tokens, "sessions": list(sessions)[:5]}

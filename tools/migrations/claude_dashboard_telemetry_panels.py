"""Move the Claude Code panels that only the telemetry fed to the conversation-based ledger.

Run once from the repository root. With the stack stopped, Claude Code's telemetry is lost, but the
conversation files keep the messages and tool results; these panels now read them through /data:

- «Por hora» (tokens, and cost by model and effort): the ledger grouped by hour, in local time.
  The effort is only known for the requests the telemetry reported ("sin telemetría" otherwise).
- «Herramientas»: calls, bytes returned and duration from the conversations. The duration is the time
  between the call and its result, which includes waiting for a permission prompt.
- «Prompts más caros»: the cost of each turn; its text only when the collector runs with PROMPT_TEXT=1.
"""
import json
import os
import sys
import urllib.parse

PATH = os.path.join("grafana", "dashboards", "claude", "claude-code.json")
BASE = "http://claude-collector:9100/data/"
INF = {"type": "yesoreyeram-infinity-datasource", "uid": "coach-claude"}
RANGE = "from=${__from}&to=${__to}&${project:queryparam}&${sessions:queryparam}"


def inf(dataset, **params):
    extra = "&".join("%s=%s" % (k.replace("__", "."), urllib.parse.quote(str(v), safe=":,/()*-_.")) for k, v in params.items())
    return {"refId": "A", "datasource": INF, "type": "json", "source": "url", "format": "table", "parser": "backend",
            "url": BASE + dataset + "?" + RANGE + ("&" + extra if extra else ""),
            "url_options": {"method": "GET", "data": ""}, "root_selector": "", "columns": []}


def hourly(p, column, value, **params):
    p["datasource"], p["targets"] = INF, [inf("usage", group="hour," + column, **params)]
    p["transformations"] = [
        {"id": "groupingToMatrix", "options": {"columnField": column, "rowField": "hour", "valueField": value}},
        {"id": "organize", "options": {"renameByName": {"hour\\%s" % column: "Hora"}}},
        {"id": "convertFieldType", "options": {"conversions": [{"targetField": "Hora", "destinationType": "time", "dateFormat": "YYYY-MM-DD HH:mm"}]}},
        {"id": "sortBy", "options": {"sort": [{"field": "Hora"}]}}]


def migrate(d):
    by_id = {}

    def walk(p):
        by_id[p["id"]] = p
        for c in p.get("panels", []):
            walk(c)
    for p in d["panels"]:
        walk(p)

    hourly(by_id[20], "model", "tokens_m", measures="tokens", calc="tokens_m:tokens/1000000")
    by_id[20]["description"] = "Tokens de cada hora (en la zona horaria del colector), separados por modelo, en millones."
    hourly(by_id[21], "model_effort", "cost", measures="cost")
    by_id[21]["description"] = ("Coste de cada hora separado por modelo y nivel de esfuerzo. El effort solo se conoce en las "
                                "peticiones que informó la telemetría; el resto aparece como «sin telemetría».")

    p = by_id[18]
    p["datasource"], p["targets"] = INF, [inf("tools", group="tool", measures="calls,bytes,duration_ms,timed", sort="-bytes",
                                              calc="tokens_k:bytes/4/1000;avg_ms:duration_ms/timed")]
    p["transformations"] = [{"id": "organize", "options": {
        "excludeByName": {"duration_ms": True, "timed": True},
        "renameByName": {"tool": "Herramienta", "calls": "Llamadas", "bytes": "Bytes devueltos", "tokens_k": "Tokens aprox.",
                         "avg_ms": "Duración media"},
        "indexByName": {"tool": 0, "calls": 1, "bytes": 2, "tokens_k": 3, "avg_ms": 4}}}]
    p["description"] = ("Por herramienta: cuántas veces se llamó, cuántos bytes devolvió (entran en el contexto y se releen en las "
                        "llamadas siguientes), esos bytes como tokens aproximados (bytes entre 4, en miles: una estimación) y cuánto "
                        "tardó de media. Sale de las conversaciones, así que incluye lo hecho con la pila parada. La duración va de la "
                        "llamada a su resultado e incluye la espera a que apruebes un permiso. Las salidas muy grandes que Claude "
                        "Code guarda aparte cuentan por la parte que queda en la conversación.")

    p = by_id[17]
    p["datasource"], p["targets"] = INF, [inf("prompts", group="prompt_id,session,project,prompt", measures="cost,messages",
                                              sort="-cost", limit=15)]
    p["transformations"] = [{"id": "organize", "options": {
        "excludeByName": {"prompt_id": True, "messages": True},
        "renameByName": {"prompt": "Texto", "session": "Sesión", "project": "Proyecto", "cost": "Coste"},
        "indexByName": {"prompt": 0, "project": 1, "session": 2, "cost": 3}}}]
    p["fieldConfig"]["overrides"] = [o for o in p["fieldConfig"]["overrides"] if o["matcher"].get("options") != "Prompt"] + [
        {"matcher": {"id": "byName", "options": "Sesión"},
         "properties": [{"id": "links", "value": [{"title": "Abrir la sesión", "targetBlank": True,
                                                   "url": "http://localhost:9100/session/${__value.raw}"}]},
                        {"id": "custom.width", "value": 320}]}]
    p["description"] = ("Los 15 turnos más caros: un prompt y todas las llamadas al modelo que lo respondieron. Sale de las "
                        "conversaciones, así que incluye lo hecho con la pila parada. El texto solo aparece si el colector arranca "
                        "con PROMPT_TEXT=1 (CLAUDE_PROMPT_TEXT=1 en .env): se lee de la conversación y se guarda solo en memoria. "
                        "Pulsa la sesión para abrirla.")
    return d


def main():
    with open(PATH, encoding="utf-8") as f:
        d = json.load(f)
    if not any(t.get("datasource", {}).get("uid") == "loki" for p in d["panels"] for t in p.get("targets", [])) and \
            "prompts?" in json.dumps(d):
        sys.exit("El dashboard ya está migrado.")
    d = migrate(d)
    d["version"] = d.get("version", 1) + 1
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    print("Migrado:", PATH)


if __name__ == "__main__":
    main()

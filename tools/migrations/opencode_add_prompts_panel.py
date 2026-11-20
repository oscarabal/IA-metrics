"""Add «Prompts más caros» and the «Texto de los prompts» switch to the OpenCode dashboard, as in Claude Code.

Run once from the repository root. The panel is placed under «Skills»; the panels below move down.
Hidden (the default), the collector sends asterisks instead of the text (/data ... mask=prompt).
"""
import copy
import json
import os
import sys

PATH = os.path.join("grafana", "dashboards", "opencode", "opencode.json")
CLAUDE = os.path.join("grafana", "dashboards", "claude", "claude-code.json")
URL = ("http://opencode-collector:9101/data/prompts?from=${__from}&to=${__to}&${project:queryparam}"
       "&group=prompt_id,session,project,agent,model,prompt&measures=cost,messages&sort=-cost&limit=15&mask=${prompt_text}")


def main():
    with open(PATH, encoding="utf-8") as f:
        d = json.load(f)
    if any(p.get("title") == "Prompts más caros" for p in d["panels"]):
        sys.exit("El dashboard ya tiene el panel.")
    with open(CLAUDE, encoding="utf-8") as f:
        c = json.load(f)
    template = next(p for p in c["panels"] if p.get("title") == "Prompts más caros")
    switch = next(v for v in c["templating"]["list"] if v["name"] == "prompt_text")

    skills = next(p for p in d["panels"] if p.get("title") == "Skills")
    y = skills["gridPos"]["y"] + skills["gridPos"]["h"]
    h = template["gridPos"]["h"]
    for p in d["panels"]:
        if p["gridPos"]["y"] >= y:
            p["gridPos"]["y"] += h
    panel = copy.deepcopy(template)
    panel["id"] = max(p["id"] for p in d["panels"]) + 1
    panel["gridPos"] = {"x": 0, "y": y, "w": 24, "h": h}
    panel["datasource"] = {"type": "yesoreyeram-infinity-datasource", "uid": "coach-opencode"}
    t = panel["targets"][0]
    t["datasource"], t["url"] = panel["datasource"], URL
    panel["transformations"] = [{"id": "organize", "options": {
        "excludeByName": {"prompt_id": True, "messages": True},
        "renameByName": {"prompt": "Texto", "project": "Proyecto", "session": "Sesión", "agent": "Agente", "model": "Modelo", "cost": "Coste"},
        "indexByName": {"prompt": 0, "project": 1, "session": 2, "agent": 3, "model": 4, "cost": 5}}}]
    for o in panel["fieldConfig"]["overrides"]:
        for pr in o["properties"]:
            if pr["id"] == "links":
                pr["value"] = [{"title": "Abrir la sesión", "targetBlank": True, "url": "http://localhost:9101/session/${__value.raw}"}]
    panel["description"] = ("Los 15 turnos más caros: un prompt y todas las respuestas del modelo a él (los subagentes cuentan aparte, "
                            "en su propia sesión). «Agente» y «Modelo» son los que más costaron en ese turno. El texto (hasta 300 "
                            "caracteres; pulsa la celda para verlo entero) se muestra u oculta con el selector «Texto de los prompts» "
                            "de arriba; oculto, el colector envía asteriscos. Un comando aparece como /nombre.")
    d["panels"].append(panel)
    d["panels"].sort(key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"]))
    d["templating"]["list"].append(copy.deepcopy(switch))
    d["version"] = d.get("version", 1) + 1
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    print("Añadido a", PATH)


if __name__ == "__main__":
    main()

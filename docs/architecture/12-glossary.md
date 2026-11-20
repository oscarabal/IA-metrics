---
title: Glossary
arc42-section: "12"
description: Términos técnicos propios de IA-metrics.
---

# Glosario

| Término | Definición |
| --- | --- |
| Colector | Servicio propio que lee los datos de una herramienta y los sirve (`claude-collector`, `opencode-collector`) |
| Perfil | Grupo de servicios de Docker Compose que se arranca por herramienta (`claude`, `opencode`) |
| Registro por petición | Una fila por respuesta del modelo con coste, tokens y contexto; base de `/data` ([ADR 0002](../adr/0002-registro-por-peticion-y-api-de-datos.md)) |
| `/data` | API JSON de cada colector que leen los dashboards con Infinity |
| Infinity | Plugin de Grafana que lee JSON por HTTP |
| Coste híbrido | Coste de una fila elegido entre telemetría, valor guardado o precio de tabla, con su `cost_source` |
| `cost_source` | Origen del coste: `telemetry` o `tool`, `computed`, `missing` |
| Precio de API | Lo que costaría una petición pagando por token, aunque se use una suscripción |
| `coach.db` | SQLite del colector de Claude Code con costes de telemetría, eventos de herramientas y sesiones archivadas |
| Informe de mejoras | Informe Markdown/JSON con hallazgos de reglas, pensado para pegarlo en un chat de IA |
| Reglas D1–D10, C1–C6, D11 | Detectores del informe: comunes, solo Claude Code y solo OpenCode |
| Oráculo de equivalencia | `tests/legacy_oracle.py`: cálculo antiguo de las series por día que los tests comparan con `/data` |
| DNS rebinding | Ataque en que una web hace que su dominio apunte a `127.0.0.1` para leer servicios locales |

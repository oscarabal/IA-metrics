---
title: Risks and Technical Debt
arc42-section: "11"
description: Riesgos de arquitectura y deuda técnica de IA-metrics, con su prioridad y mitigación.
---

# Riesgos y deuda técnica

| Riesgo o deuda | Impacto | Evidencia | Prioridad | Mitigación o decisión |
| --- | --- | --- | --- | --- |
| Formatos ajenos sin contrato (conversaciones de Claude Code, esquema de `opencode.db`) | Datos que dejan de contarse sin error visible | Lectura por nombres de campo en `index.py` y SQL de `exporter.py` | Alta | Lectura tolerante y tests con datos de ejemplo; `tools/check_claude_prices.py --fields` para revisar campos reales |
| Relectura completa de las conversaciones al arrancar | Minutos con «PENDIENTE» en historiales grandes | `index.scan_files`; decisión de no persistir el índice por privacidad | Media | Progreso visible en `/health` y `/prices/missing`; aceptado |
| Precios que se desactualizan | Coste `missing` o aproximado | `prices.json` a mano; models.dev sin periodos ni modo rápido | Baja | models.dev como respaldo ([ADR 0006](../adr/0006-precios-de-claude-code-desde-models-dev.md)); panel y aviso de «Modelos sin precio» |
| Cuerpo de las reglas D1–D10 escrito dos veces | Un cambio de lógica o de texto se hace en los dos colectores | `coach/report.py` en ambos; datos distintos en cada uno | Baja | Umbrales, severidad, catálogo y forma comunes en `common/coach_rules.py`; `tests/test_contract.py` lo comprueba |
| Coste del informe de OpenCode distinto del de los dashboards | Cifras que no cuadran | `coach/report.py` suma el coste guardado ([ADR 0005](../adr/0005-coste-de-opencode-a-precio-de-api.md)) | Media | Usar `api_prices.hybrid` en el informe |
| El colector de OpenCode puede leer `auth.json` | Claves expuestas ante un fallo de lectura de ficheros | Montaje de toda la carpeta de datos de OpenCode | Baja | Ninguna ruta sirve ficheros; montar solo `opencode.db*` (auditoría #6) |
| Contenedores como root y sin endurecer | Mayor impacto de un fallo de los colectores | `docker-compose.yml` | Baja | `user`, `read_only`, `cap_drop` (auditoría #7) |
| Títulos de sesión en etiquetas de Prometheus | Texto de conversaciones guardado 365 días | `map.py` y `exporter.py` (`label=`) | Baja | Usar id de sesión y proyecto (auditoría #4) |
| Sin copias de seguridad de los volúmenes | Pérdida de historial de `coach.db` y Grafana | Herramienta local de un usuario | Baja | Aceptado (README, «Limitaciones») |

Detalle de los hallazgos de seguridad: auditoría del 20-11-2026 en el proyecto de Claude.

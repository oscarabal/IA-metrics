---
title: Crosscutting Concepts
arc42-section: "08"
description: Mecanismos comunes a varios bloques: privacidad, coste, seguridad de red, trabajo en segundo plano y pruebas.
---

# Conceptos transversales

## Privacidad: solo metadatos

### Alcance

Ambos colectores y `coach.db`.

### Mecanismo

- De las conversaciones se leen tokens, modelos, nombres de herramientas, skills y comandos, títulos y rutas.
  En disco solo acaba el archivo de sesiones de `coach.db`, sin `title`, `cwd`, `branch` ni `prompts`
  (`_NOT_ARCHIVED` en `coach/store.py`).
- El texto de los errores se clasifica en memoria (`coach/errors.py`) y se descarta.
- El texto de los prompts (300 caracteres) vive solo en memoria; `/data` lo sustituye por asteriscos con
  `mask=prompt`, que es lo que piden los dashboards por defecto. `CLAUDE_PROMPT_TEXT=0` evita leerlo.
- De la telemetría solo se usan `api_request`, `tool_result` y `tool_decision`; de un resultado de herramienta,
  su tamaño y duración.
- Por esta regla, el índice de Claude Code no se persiste y se relee al arrancar ([11](11-risks-and-technical-debt.md)).

### Evidencia

`tests/test_claude.py` (`test_usage_survives_deleted_conversations`, `test_prompt_text_opt_in_never_archived`).

## Coste híbrido

### Alcance

`/data`, páginas de sesión, `/prices` y dashboards de las dos herramientas.

### Mecanismo

Cada fila de `usage` lleva `cost` y `cost_source`, decididos en un único punto por herramienta:

| Herramienta | `telemetry` / `tool` | `computed` | `missing` |
| --- | --- | --- | --- |
| Claude Code (`index.hybrid_cost`) | Coste del evento de telemetría | Tokens × `prices.json` o, si no está, × la copia de models.dev ([ADR 0006](../adr/0006-precios-de-claude-code-desde-models-dev.md)) | Modelo sin precio en ninguna |
| OpenCode (`api_prices.hybrid`) | Coste que guardó OpenCode | Tokens × precio de `models.json` (proveedor o fabricante) | Sin precio en ningún sitio |

El coste es siempre a precio de API, también con suscripción ([ADR 0002](../adr/0002-registro-por-peticion-y-api-de-datos.md),
[ADR 0005](../adr/0005-coste-de-opencode-a-precio-de-api.md)). Los modelos sin precio se publican
(`*_model_without_price_messages`) para el panel «Modelos sin precio».

### Evidencia

`tests/test_claude.py` (`test_hybrid_cost`, `test_models_without_price`), `tests/test_opencode.py`
(`test_api_cost_of_zero_cost_messages`), `tests/test_pricing.py`.

## Seguridad de red local

### Mecanismo

- Solo Grafana, los colectores y el 4317 se publican, en `127.0.0.1`.
- Los colectores rechazan con 421 una cabecera `Host` desconocida (`common/security.py`), contra DNS
  rebinding; `ALLOWED_HOSTS` añade nombres.
- Grafana con usuario y contraseña de `.env`, sin acceso anónimo; Infinity limitado a los colectores.

### Evidencia

`tests/test_config.py` (`test_ports_loopback_only`, `test_infinity_urls_allowed`), pruebas de `Host` en cada colector.

## Trabajo en segundo plano

### Mecanismo

Las lecturas caras (conversaciones, `opencode.db`, Loki, hallazgos del informe) se hacen en hilos de fondo
y se guardan en caché; las peticiones HTTP copian lo calculado. El informe cachea 120 s por parámetros.

### Evidencia

`tests/test_opencode.py` (`test_scrape_reads_no_database`).

## Frescura de los datos y salud del canal

### Mecanismo

- Cada colector publica en `/metrics` cuándo vio la última actividad de su fuente y cuándo la leyó con éxito
  (conversaciones y telemetría de Claude Code, `opencode.db`). Prometheus lee además las métricas internas del
  OTel Collector (recibido, rechazado, no enviado a Loki) y de Loki (líneas guardadas).
- La fila «Estado de las fuentes» del Resumen IA lo junta: distingue un periodo sin actividad de una fuente que no llega.
- Los gráficos en el tiempo piden `group=auto`: el tamaño de grupo sigue al rango y ningún punto queda antes de su
  inicio, así que un rango corto (15 minutos) no sale vacío si hay datos.

### Evidencia

`tests/test_claude.py` y `tests/test_opencode.py` (`test_source_freshness`), `tests/test_common.py` (`AutoBuckets`),
`tests/test_config.py` (`test_telemetry_pipeline_observed`).

## Código común y contrato entre colectores

Lo idéntico en los dos colectores vive en `collectors/common/`; `/data` tiene las mismas columnas en ambos
(si se añade una, se añade en los dos), y el informe comparte reglas D1–D10 y formato JSON
(`tests/test_contract.py`). Cada colector escribe sus reglas sobre sus propios datos, pero el catálogo, los
umbrales de D1–D10, la severidad y la forma de un hallazgo vienen de `common/coach_rules.py`, y un test
comprueba que los dos informes lo usan.

# CLAUDE.md

Guía para Claude Code en este repositorio.

## Qué es

Pila local de observabilidad (Docker Compose) para medir uso y coste de Claude Code y OpenCode. Fusiona
los antiguos `claude-metrics` y `opencode-metrics`. No hay paso de compilación ni gestor de paquetes: los
colectores son Python de la librería estándar ejecutado en `python:3.13-alpine`, con `collectors/`
montado en `/srv` en solo lectura y `PYTHONPATH=/srv`.

## Comandos

```bash
docker compose up -d                                    # perfiles según COMPOSE_PROFILES en .env
docker compose --profile claude --profile opencode config   # validar el compose con todo activado
docker compose restart grafana                          # aplicar cambios en grafana/dashboards (provisionados)
docker compose restart claude-collector opencode-collector  # aplicar cambios en collectors/
docker compose up -d --force-recreate otel-collector    # aplicar cambios en config/otel-collector.yaml
```

## Estructura

- `collectors/common/` — código compartido: `ledger.py` (motor de consultas y API `/data`, ADR 0002),
  `security.py` (cabecera Host), `report_page.py` (página del informe), `html_page.py` (CSS y helpers de las
  páginas), `markdown.py` (formato del informe), `coach_rules.py` (catálogo de reglas, umbrales de D1–D10,
  severidad y forma de un hallazgo: los dos `coach/report.py` los importan; un umbral se cambia solo ahí).
- `collectors/*/ledger_source.py` — el registro por petición de cada herramienta: los conjuntos de
  datos que sirve `/data`. Mismas columnas en las dos; si añades una, añádela en ambas.
- `collectors/claude/prices.json` + `pricing.py` — tabla de precios versionada por fecha (y, para los modelos que
  no están, la copia diaria de models.dev en `/state/models-dev.json`, ADR 0006) para el coste
  de Claude Code sin telemetría. `index.hybrid_cost` es el único punto que decide el coste.
- `collectors/claude/` — antiguo `session-map`: `map.py` (HTTP :9100), `index.py` (lectura incremental
  de las conversaciones: tokens, effort, herramientas, permisos, prompts), `pages.py`, `coach/` (informe,
  reglas D1–D10 + C1–C6; `store.py` = `coach.db`, archivo de sesiones y costes de la telemetría, con retención `COACH_RETENTION_DAYS` y VACUUM diario).
- `collectors/opencode/` — antiguo `exporter`: `exporter.py` (HTTP :9101, lectura de `opencode.db`),
  `session_page.py`, `api_prices.py` (precio de API de models.json para los mensajes que OpenCode guarda con
  coste 0: `hybrid` es el único punto que decide el coste de `/data`), `coach/` (reglas D1–D11).
- Modelos sin precio: los dos colectores sirven `/prices` (página) y `/prices/missing` (texto: `OK`,
  `SIN PRECIO` o `PENDIENTE`, que lee `Iniciar-metricas.bat`) y publican
  `claude_model_without_price_messages` / `opencode_model_without_price_messages` (panel «Modelos sin precio»).
- Documentación de usuario: `README.md` y `README.en.md` (paralelos: se actualizan juntos; diagramas
  Mermaid), `docs/claude-code.md` y
  `docs/opencode.md` (cada panel y de dónde sale). Si cambias un panel, actualiza su guía.
- `config/` — OTel Collector, Loki, Prometheus y provisioning de Grafana.
- `grafana/dashboards/{global,claude,opencode}` — una carpeta de Grafana por subcarpeta.
- `installer/install.ps1` — instalador (Windows PowerShell 5.1 compatible; ficheros con CRLF y BOM), también
  `-Update` y `-Uninstall` (`Actualizar.bat`, `Desinstalar.bat`). Desinstalar solo quita de `settings.json` las
  variables que el instalador puso y con su valor (`tests/installer_uninstall.ps1`).

## Convenciones que hay que respetar

- **Privacidad.** Los colectores nunca persisten texto de conversaciones, prompts o errores (los errores
  solo se clasifican en memoria). De la telemetría solo se leen `api_request`, `tool_result` y
  `tool_decision`; el instalador no ofrece `OTEL_LOG_USER_PROMPTS` porque nada lo usa.
  `coach/store.py` archiva cada sesión del índice (`session_archive`) sin `title`, `cwd` ni `branch`
  (`_NOT_ARCHIVED`, que incluye `prompts`); un campo nuevo del índice con texto o rutas debe añadirse ahí.
  El texto de los prompts (ambos colectores) vive solo en memoria y la API lo sustituye por asteriscos
  con `mask=prompt`, que es lo que piden los dashboards por defecto. Del resultado
  de una herramienta solo se guardan su tamaño y su duración. De `~/.claude` solo se montan `projects`, `commands` y `skills`, en solo
  lectura; nunca `settings.json`. El instalador es lo único que lo modifica, con confirmación y copia.
- **Puertos solo en 127.0.0.1** (no hay autenticación en collector, Loki, Prometheus ni colectores), y los
  colectores validan la cabecera `Host` con `common/security.py`: todo endpoint nuevo pasa por ahí.
  Prometheus, Loki y los puertos 4318/8889 del collector no se publican (no validan `Host`): solo con
  `docker-compose.debug.yml`. No vuelvas a publicarlos en `docker-compose.yml`.
- **Logs de Docker limitados** (`x-logging`); no dejar el exportador `debug` activo en el collector.
- **Healthchecks:** Prometheus, Grafana y los dos colectores (`/health`, ligero: no lo conviertas en una
  lectura de datos). Loki y el OTel Collector no tienen shell en su imagen y van sin healthcheck.
  `Iniciar-metricas.bat` y el instalador esperan con `docker compose up -d --wait`.
- **Versiones de imagen fijadas**, nunca `latest`.
- **Dashboards provisionados:** se editan en el JSON, no en la UI; el global se genera con
  `tools/dashboards/global_overview.py`. Datasources Infinity: `coach-claude` y `coach-opencode`.
  Los paneles nuevos leen `/data` (no series por día en Prometheus); `tests/test_*` comprueban que cada
  URL de cada dashboard devuelve los campos que el panel usa.
- **Sin series por día en Prometheus:** las `*_day_*`/`*_week_*` se retiraron (ADR 0002); su cálculo vive
  solo en `tests/legacy_oracle.py`, como oráculo de los tests de equivalencia. No lo importes desde los colectores.
- **Frescura de las fuentes:** cada colector publica cuándo vio la última actividad y cuándo leyó su fuente
  (`claude_index_last_*`, `claude_telemetry_last_*`, `opencode_last_message_*`, `opencode_db_read_*`, en segundos), y
  Prometheus lee las métricas internas del OTel Collector (`:8888`) y de Loki, sin publicarlas. Las usa la fila «Estado
  de las fuentes» del Resumen IA; una fuente nueva publica las suyas.
- **Gráficos en el tiempo con `group=auto`:** la API elige el tamaño de grupo según el rango y nunca da un `time`
  anterior a `from`; los paneles de evolución lo usan para no quedar vacíos con rangos cortos.
- **El scrape no lee datos:** `/metrics` de OpenCode sirve lo que calcula el hilo de fondo (`refresh_series`,
  cada `SERIES_SECONDS`); el de Claude Code, lo que ya tiene el índice en memoria.
- **Código común en `collectors/common/`:** `html_page.py` (CSS y helpers de las páginas) y `markdown.py`
  (formato del informe; `cell` deja cada celda en una línea). Lo que sea igual en los dos colectores va ahí.
- **Tablas de una línea por fila:** sin `wrapText` ni `cellHeight: lg`, y con `noValue` propio en las
  columnas estrechas (Grafana rellena las celdas vacías con el `noValue` del panel); los tests lo vigilan.
- El texto del informe de mejoras siempre en español.
- Las decisiones de arquitectura van en `docs/adr/`; la documentación arc42 está en `docs/architecture/`
  (skill `architecture-docs`): un cambio que toque contexto, bloques, despliegue, coste o privacidad actualiza
  la sección que lo explica.

## Tests

```bash
python tests/run.py              # todas las suites, cada una en su proceso
python tests/run.py opencode     # solo las que contienen "opencode"
```

- `tests/fixtures.py` genera datos deterministas de ambas herramientas (conversaciones de Claude Code,
  `opencode.db`); `tests/fake_loki.py` sirve la telemetría de Claude. Las cifras esperadas se derivan
  de las constantes de `fixtures.py`, nunca se escriben dos veces.
- Cada colector se prueba en su propio proceso: ambos tienen un paquete `coach`.
- `test_config.py` necesita PyYAML; la comprobación del instalador necesita `pwsh` (se salta si no está).

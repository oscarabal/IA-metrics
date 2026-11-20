# ADR 0002: Registro por petición en cada colector y API JSON de datos para Grafana

- **Estado:** aceptada
- **Fecha:** 2026-11-20
- **Sustituye a:** las propuestas 0002 (datos por día de OpenCode como tablas) y 0003 (fuente única del
  coste de Claude Code), que se fusionan aquí porque se resuelven con el mismo diseño.

## Contexto

Análisis del código a 2026-11-20:

- **Prometheus usado como almacén de tablas.** Los dos colectores publican todo su historial en cada
  scrape con el día o la semana como etiqueta (`opencode_day_*`, `opencode_weekly_*`, `claude_day_*`,
  `claude_coach_day_*`, `claude_coach_week_*`) y filtran fechas con `*_day_start_seconds`. Los 26 paneles
  de OpenCode y 24 de los 27 de Claude Code hacen solo consultas instantáneas: Prometheus guarda 365 días
  de copias idénticas que ningún panel lee. La cardinalidad crece con el historial.
- **Tres fuentes de coste en Claude Code.** Contadores OTel por `session_id` (10 paneles; caducan a las
  24 h, no llevan proyecto y exigen una consulta frágil), eventos `api_request` de Loki guardados en
  `coach.db` (coste por comando, semanal e informe) y las conversaciones (tokens, sin coste). Nada
  comprueba que coincidan.
- **Huecos silenciosos.** La telemetría de Claude Code se pierde si la pila no está en marcha; las
  conversaciones quedan en disco. Por eso Claude «no tiene historial» antes de activar la telemetría.
- **Días en UTC.** OpenCode y Claude agrupan por día UTC; el usuario está en Europe/Madrid.

## Decisión

1. **Registro por petición en cada colector.** Una fila por respuesta del modelo con las mismas columnas
   en ambas herramientas: `ts`, `session`, `project`, `provider`, `model`, `agent`, `cost`,
   `cost_source`, `input`, `output`, `reasoning`, `cache_read`, `cache_write`; y registros de eventos
   (sesiones, llamadas a herramientas, compactaciones, interrupciones, skills y comandos).
   - **OpenCode:** se construye desde `opencode.db` (el colector ya lo carga en memoria para el informe).
     `cost_source = tool` (el coste que guarda OpenCode).
   - **Claude Code (híbrido):** se construye desde las conversaciones, que tienen todo el historial y el
     proyecto. El coste viene del evento `api_request` (Loki/`coach.db`) cuando existe
     (`cost_source = telemetry`) y, si no, de una tabla de precios versionada (`computed`). Un modelo sin
     precio queda como `missing`, nunca como 0.
2. **API JSON común** (`collectors/common/ledger.py`, rutas `/data/*`): filtra por `from`/`to` (ms),
   proyecto y campos; agrupa por cualquier columna y por `hour`/`day`/`week` en la zona horaria `TZ`
   (por defecto `Europe/Madrid`); suma las columnas numéricas. Pasa por la validación de `Host`.
3. **Grafana lee la API con Infinity**, con el selector de tiempo de Grafana (`${__from}`/`${__to}`).
4. **Prometheus se queda con lo que sí es temporal:** OTel por hora y equipo, contexto de sesiones,
   cuotas y salud de los colectores.
5. **Transición en paralelo:** las métricas `*_day_*`/`*_week_*` se siguen publicando hasta que los
   dashboards migrados cuadren con ellas (tests de equivalencia); después se retiran
   (`LEGACY_DAY_METRICS=0`). El origen de cada coste queda en la API (`cost_source`, `cost_telemetry`,
   `cost_computed`) para consultarlo cuando haga falta.

## Alternativas descartadas

- **Backfill en Prometheus con marcas de tiempo reales:** TSDB es de solo añadir y rechaza muestras
  antiguas; OpenCode reescribe mensajes ya guardados.
- **Plugin SQLite de Grafana sobre `opencode.db`:** acopla dashboards al esquema interno de OpenCode,
  expone a Grafana la carpeta con `auth.json` y es lento sobre el bind mount de Windows.
- **Plugin SQLite sobre una base propia:** viable, pero el contrato pasa a ser el esquema SQL repartido
  por los dashboards y añade otro plugin; la API mantiene la privacidad y el contrato en código probado.
- **Solo contadores OTel o solo Loki para Claude:** heredan los huecos de la telemetría.

## Consecuencias

- Historial completo de ambas herramientas en el dashboard global, en hora local.
- Menos series en Prometheus; su retención se puede revisar al final de la migración.
- Más código propio (API, tabla de precios) y más dependencia de Infinity.
- La tabla de precios hay que mantenerla; el diagnóstico mide su desviación frente a la telemetría.
- Requiere la suite del ADR 0004 como red de seguridad.

## Implementación (2026-11-20)

- `collectors/common/ledger.py` (API), `collectors/*/ledger_source.py` (registros),
  `collectors/claude/prices.json` y `pricing.py` (tabla de precios con fechas, tramos, modo rápido,
  inferencia en EE. UU. y búsqueda web), `index.hybrid_cost` (un solo punto para el coste).
- Dashboards de Claude Code y OpenCode migrados con `tools/migrations/*.py`; el global, generado con
  `tools/dashboards/global_overview.py`. 
- Equivalencia: los tests comparan la API con todas las series por día/semana sobre datos de ejemplo.
  Con una `opencode.db` real de 1,15 GB (`tools/check_opencode_equivalence.py`) las 17 series
  coinciden; 5.776 de las 6.640 series de OpenCode en Prometheus son las que se retiran.
- Pendiente: validar en Grafana, ejecutar `tools/check_claude_prices.py` sobre conversaciones reales,
  revisar la desviación de precios en el diagnóstico y después `LEGACY_DAY_METRICS=0`.
- 2026-11-20, tras la primera puesta en marcha: la desviación de la tabla de precios frente a la
  telemetría es 0,0 % en los cuatro modelos usados (~1.400 peticiones). Los contadores OTel daban un
  15 % menos que el registro para las mismas peticiones (98,54 $ frente a 115,90 $), como se esperaba
  de su consulta por sesión; el panel que los comparaba se retiró por no aportar más.
- Después se retiró también la fila «Diagnóstico del coste»: con la pila casi siempre en marcha marcaba 0 casi
  siempre. El origen del coste sigue en la API (`/data/usage?group=cost_source`) y los modelos sin precio
  se detectan con `tools/check_claude_prices.py`; un aviso automático queda para las alertas.
- Persistencia del registro de Claude Code: el índice se reconstruía desde las conversaciones en cada
  arranque, y Claude Code las borra pasados `cleanupPeriodDays` (30 días por defecto), con lo que el
  historial del dashboard encogía. `coach/store.py` archiva ahora cada sesión (solo metadatos) y al
  arrancar restaura las que ya no tienen fichero; las que lo tienen se leen del fichero, sin duplicar. El
  instalador ofrece además subir `cleanupPeriodDays` a 90 días (por defecto, no).
- Paneles que solo alimentaba la telemetría, pasados al registro para que la pila parada no deje huecos:
  «Por hora» (registro agrupado por hora; el effort solo donde hubo telemetría), «Herramientas»
  (llamadas, bytes y duración leídos de los resultados en las conversaciones, sin guardar su contenido) y
  «Prompts más caros» (coste por turno; el texto solo con `PROMPT_TEXT=1`, en memoria). El dashboard de
  Claude Code ya no consulta Loki ni los contadores OTel; la telemetría sigue aportando el coste exacto,
  el effort, las llamadas que no se escriben en la conversación y las decisiones de permisos del informe.
  `tools/check_claude_prices.py --fields` sirve para comprobar si las conversaciones o `stats-cache.json`
  permiten recuperar el effort o esas llamadas.
- Con los campos reales de las conversaciones (`check_claude_prices.py --fields`): Claude Code escribe en
  cada respuesta el effort (`effort`, 95 % de las respuestas) y en cada resultado la decisión de permisos
  (`permissionDecision`), `durationMs` y `persistedOutputSize`. El registro y el informe los usan cuando
  falta la telemetría. `stats-cache.json` no sirve (12 días, modelos antiguos, sin coste por día): el coste
  de las llamadas que no se escriben en la conversación solo llega por la telemetría.
- «Prompts más caros» en ambos dashboards, con el texto siempre leído (solo en memoria) y un selector
  «Texto de los prompts» (por defecto, oculto) que pide a la API `mask=prompt`: el texto oculto se
  sustituye por asteriscos en el colector, no en Grafana, para que no llegue al navegador (ni a «Inspect»
  ni a una descarga CSV). Con la `opencode.db` real: 1.628 turnos, 95 % con texto, el coste de los turnos
  cuadra con el total (188,19 $), primera lectura 0,6 s y consulta del panel 11 ms.
- 2026-11-20, retirada: las series `*_day_*`/`*_week_*` (y `LEGACY_DAY_METRICS`, las agregaciones diarias de
  Loki en `coach.db` y `tools/check_opencode_equivalence.py`) se quitan de los colectores. Su código pasa,
  sin cambios, a `tests/legacy_oracle.py`: los tests de equivalencia siguen comparando la API con esa
  segunda implementación. Los scripts de `tools/migrations/`, ya aplicados, se borran.

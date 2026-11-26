# ADR 0010: Compatibilidad con OpenCode 2.x mediante vistas temporales con la forma de 1.x

- **Estado:** aceptada
- **Fecha:** 2026-11-26

## Contexto

Al actualizar OpenCode a la 2.4.2 el dashboard de OpenCode dejó de mostrar datos. OpenCode 2.x cambió
por completo su base de datos local (`~/.local/share/opencode/opencode.db`):

| 1.x | 2.x |
| --- | --- |
| `session` | `session_v2` (con coste y tokens agregados por sesión) |
| `message` (`data.role` = user/assistant) | `session_message` (`type` = user, assistant, compaction, synthetic, skill, shell, idle…; `seq` por sesión) |
| `part` | `session_part` (contenido del asistente: text, reasoning, tool); los mensajes importados de 1.x lo guardan en línea en `session_message.data.content` |
| `providerID`, `modelID`, `parentID` | `model.providerID`, `model.id`; no hay `parentID` |
| `error.name` (`MessageAbortedError`…) | `error.type` (`aborted`…) y `error.message` |
| Herramienta `tool`, `state.error` como texto | `name`, `state.error.type` / `state.error.message`; estado `streaming` |
| Skill: `state.input.name` | `state.input.id` (el nombre, en `state.metadata.name`); además, mensajes `skill` cuando el usuario carga una |
| Compactación: mensaje de usuario con parte `compaction` + respuesta resumen de agente `compaction` | Un mensaje `compaction` con su propio modelo, coste y tokens |
| `~/.cache/opencode/models.json` (`cost.input`, `cost.cache_read`…) | Tabla `kv`, clave `models-dev:v3:catalog` (`cost.text.input.price`, `cost.text.input.cache.write` por TTL…) |

El colector abría la base de datos comprobando `select 1 from message`, que fallaba, así que no publicaba
nada. Además faltaba `models.json`, del que salen los precios de API (ADR 0005) y los límites de contexto.

OpenCode 2.x importa el historial de 1.x **dentro del mismo fichero** cuando encuentra la tabla `session`, y
conserva las tablas antiguas. Si la versión anterior se desinstala borrando su carpeta de datos, la 2.x crea
un `opencode.db` vacío y el historial anterior se pierde (salvo copia de seguridad).

## Opciones consideradas

1. **Reescribir todas las consultas** (unas 25 en `exporter.py`, `coach/` y el oráculo de pruebas) para 2.x,
   y mantener las de 1.x aparte.
2. **Vistas temporales con la forma de 1.x**: al conectar, si la base de datos es 2.x, crear en el esquema
   `temp` de la conexión las vistas `session`, `message` y `part` sobre las tablas nuevas.
3. **Copiar los datos** a una base de datos propia con el esquema de 1.x.

## Decisión

Opción 2, en `collectors/opencode/oc_schema.py` (`adapt(conn)`, llamado desde `exporter.connect()`):

- **Detección:** 2.x si existe `session_v2`; 1.x si no, o si `session_v2` está vacía y la `session` antigua
  no (importación pendiente). Con ambas pobladas ganan las tablas nuevas.
- **`message`:** `assistant` y `compaction` como respuestas del asistente (la compactación con agente
  `compaction` y `parentID` = su propio id, como contaba 1.x su coste); `user` y `synthetic` como mensajes de
  usuario; `skill` con rol `skill`. `parentID` = el último mensaje `user` anterior de la sesión (por `seq`).
  Los `error.type` que el informe trata aparte se traducen al nombre de 1.x (`aborted` → `MessageAbortedError`,
  `provider.invalid-request` de contexto → `ContextOverflowError`…).
- **`part`:** filas de `session_part` (tool y text), contenido en línea de mensajes importados, el texto de
  cada mensaje de usuario (y el sintético marcado `synthetic`), una parte `compaction` por compactación y una
  llamada `skill` por cada skill cargada por el usuario. Los errores de herramienta se convierten en el texto
  que clasifica `coach/errors.py`. El id es `prt_<ms de 13 dígitos>_<mensaje>_<ordinal>`, que crece con el
  tiempo como los de 1.x, para que la lectura incremental por id siga funcionando.
- **Catálogo de models.dev:** `collectors/opencode/catalog.py` lee `models.json` si existe y, si no, la tabla
  `kv` de `opencode.db`, y lo normaliza a la forma de 1.x. Lo usan `api_prices` y los límites de contexto.

Las vistas viven en el esquema temporal de cada conexión: no se escribe nada en `opencode.db`, que sigue
montado en solo lectura.

## Consecuencias

- El colector funciona con OpenCode 1.x y 2.x sin cambiar consultas, dashboards ni la API `/data`.
- `tests/test_opencode_v2.py` pasa la suite completa de OpenCode contra una base de datos con el esquema real
  de 2.4.2 (`tests/opencode_v2_schema.sql`, copiado de un `opencode.db` real); `tests/test_opencode_schema.py`
  prueba la detección, el contenido en línea, el catálogo y que no se escribe nada.
- En 2.x cada compactación cuenta como un mensaje del asistente más (agente `compaction`), igual que en 1.x
  contaba la respuesta resumen.
- Coste de lectura: las vistas construyen el JSON de 1.x en cada consulta. Con 48 000 mensajes y 144 000
  partes (300 MB) la primera lectura tarda 3–5 s y cada lectura incremental del hilo de fondo ≈1 s. En las
  consultas incrementales la condición por id va primero, para descartar lo ya leído antes de construir JSON.
- El esquema de OpenCode sigue sin contrato (riesgo en `docs/architecture/11`). Al subir de versión:
  regenerar `tests/opencode_v2_schema.sql` desde un `opencode.db` real y pasar `python tests/run.py opencode`.
- No se leen aún datos nuevos de 2.x (`time.firstToken`, `rawFinish`, `job` de subagentes, coste agregado de
  `session_v2`, mensajes `shell`).

## Alternativas descartadas

- **Opción 1:** duplica cada consulta y el riesgo de que las dos versiones den cifras distintas.
- **Opción 3:** necesita una copia sincronizada y escribir en disco; más piezas para el mismo resultado.

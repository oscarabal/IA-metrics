# ADR 0007: Tareas de la app de Claude con un colector propio que recibe su telemetría

- **Estado:** retirada (implementada y quitada el mismo día, 2026-11-21)
- **Fecha:** 2026-11-21

> **Por qué se retiró.** La telemetría de la app solo la puede activar un administrador de un plan Team o
> Enterprise en *Admin settings > Cowork*, y el usuario no tiene ese acceso: el colector nunca recibiría
> datos. Además, la dirección que ve la máquina virtual de cada tarea no se pudo verificar. Se quitó el código
> (`collectors/app/`, dashboard `claude-app`, perfil `app`, opción del instalador y tests) para no mantener un
> tercer colector ni la excepción a «solo 127.0.0.1» sin uso. Lo que sí se usa de la app, la pestaña Code, ya
> lo mide `claude-collector`. Si algún día hay acceso de administrador, este ADR describe el diseño para
> recuperarlo (el código está en el historial de la conversación, no en git: nunca se confirmó).

## Contexto

El usuario también trabaja con la app de Claude (escritorio y web) y quiere que su uso cuente junto al de
Claude Code y OpenCode. A diferencia de esas dos herramientas, la app no deja en el equipo nada que se pueda leer:

- **Pestaña Code de la app:** es Claude Code y escribe en `~/.claude/projects`; `claude-collector` ya la cuenta.
- **Tareas (Cowork):** exportan eventos OpenTelemetry (logs) cuando un administrador configura un endpoint
  en *Admin settings > Cowork*. Solo en planes Team y Enterprise. La configuración vale para toda la
  organización. Los eventos son `user_prompt`, `assistant_response`, `api_request` (modelo, tokens,
  `cost_usd`, duración), `api_error`, `tool_result` y `tool_decision`; el recurso lleva `service.name=cowork`.
  Protocolo `http/json` o `http/protobuf` (no gRPC), con cabeceras para autenticarse. El exportador
  se ejecuta **dentro de la máquina virtual de la tarea**, no en Windows. `api_request` no lleva `request_id`.
  Los eventos llevan siempre `user.email` y las rutas de las carpetas conectadas (`workspace.host_paths`), y
  con la captura de contenido activada, el texto de los prompts, las respuestas y las entradas de las herramientas.
- **Chats normales de claude.ai:** no tienen telemetría. La Analytics API (Enterprise) da agregados, no peticiones.
- **% del límite del plan:** solo un endpoint no documentado de claude.ai con la sesión del usuario; se descarta.

Fuente: <https://claude.com/docs/cowork/monitoring>.

## Decisión

1. **Un colector propio, `app-collector`** (`collectors/app/`, perfil `app`), en Python de la librería
   estándar como los otros dos. Recibe directamente el OTLP/HTTP JSON (`POST /v1/logs`, puerto 4319) y
   guarda los eventos en su propia SQLite (`app.db`, volumen `app-data`). No pasa por el OTel Collector ni por Loki.
2. **Privacidad en la entrada** (`otlp.py`): solo pasan `api_request`, `api_error`, `tool_result` y
   `tool_decision`, y de cada uno una lista cerrada de metadatos. Nunca se guardan el texto de prompts y
   respuestas, `tool_input`, `tool_parameters`, el texto de los errores, `user.email`, los identificadores
   de cuenta ni las rutas. De las carpetas solo queda el nombre del proyecto (la regla de Claude Code:
   subcarpeta de `PROJECT_ROOTS` o última carpeta).
3. **Token obligatorio:** cada petición necesita `Authorization: Bearer <APP_OTLP_TOKEN>` (mínimo 16
   caracteres; el instalador genera 40). Sin token configurado, el receptor lo rechaza todo. Solo se
   admite `http/json` (protobuf necesitaría una dependencia; responde 415 y lo dice en el log).
4. **Dos puertos:** el receptor (4319) no sirve datos: solo acepta `POST`. La API `/data`, `/health` y
   `/metrics` (9102) siguen la norma de todos los colectores: `127.0.0.1` y validación de `Host`. El
   receptor se publica en `127.0.0.1` por defecto, y `APP_OTLP_BIND` permite abrirlo en otra interfaz si la
   máquina virtual de la tarea no llega a esa dirección. Esa es la única excepción a «solo 127.0.0.1», y la
   cubren el token y que el puerto no devuelva nada.
5. **Mismo contrato `/data`** (`usage`, `sessions`, `tools`, `errors`): el dashboard global suma una
   tercera herramienta, «Claude (app)», sin código especial. Dashboard propio `claude-app`.
6. **Reintentos sin duplicar:** cada evento tiene una clave (sesión + evento + `event.sequence`); un lote reenviado se ignora.

## Alternativas descartadas

- **Reutilizar `otel-collector` + Loki** (como la telemetría de Claude Code): habría que publicar un
  puerto OTLP HTTP sin validación de `Host`, autenticar con la extensión `bearertokenauth` (en Compose no
  se puede exigir el token solo cuando el perfil está activo), filtrar el texto con OTTL antes de Loki
  (difícil de probar en la suite) y separar en `claude-collector` los `api_request` de las dos fuentes.
  Además, Loki solo guarda 30 días.
- **Leer el endpoint no documentado del límite del plan:** frágil, exige guardar una credencial de
  claude.ai y no da ni coste ni tokens.
- **Analytics API de Enterprise:** solo agregados por día y usuario, solo Enterprise y con clave de propietario.

## Consecuencias

- Las tareas de la app aparecen en el resumen global y en su propio dashboard, con historial propio.
- **Sin verificar en un equipo real** al escribir este ADR: falta confirmar qué dirección de Windows ve la
  máquina virtual de la tarea (`APP_OTLP_BIND` y endpoint). El panel «Recepción de la telemetría» y
  `/health` de `app-collector` dicen si llegan eventos, y el log, por qué se rechazan.
- Las tareas que se ejecutan en la nube no pueden llegar a un colector local; los chats no se miden.
- El coste es el `cost_usd` que calcula la propia app (precio de API), no lo que se paga con el plan.
- La configuración de *Admin settings* afecta a toda la organización: con varios usuarios, cada uno
  necesitaría su propio IA-metrics y el mismo token, o un colector compartido.

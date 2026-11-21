# ADR 0006: models.dev como respaldo de los precios de Claude Code

- **Estado:** aceptada
- **Fecha:** 2026-11-21

## Contexto

El coste de Claude Code sin telemetría se calcula con `collectors/claude/prices.json`, que se mantiene a
mano ([ADR 0002](0002-registro-por-peticion-y-api-de-datos.md)). Cuando sale un modelo nuevo, sus mensajes
quedan con coste `missing` hasta que alguien lo añade, y el panel «Modelos sin precio» se pone en rojo.
OpenCode ya valora sus mensajes con el catálogo público de models.dev ([ADR 0005](0005-coste-de-opencode-a-precio-de-api.md)),
pero solo si OpenCode está instalado.

## Decisión

`prices.json` sigue siendo la fuente principal, la única con periodos, tramos, modo rápido y recargo de
EE. UU. Para un modelo que no está en ella:

- `claude-collector` descarga una vez al día `MODELS_DEV_URL` (por defecto `https://models.dev/api.json`) en
  el volumen `coach-data` (`/state/models-dev.json`), con escritura atómica y un límite de tamaño.
- `pricing.period_for` usa el precio de ese catálogo, buscando el modelo por nombre en los proveedores de
  `DEV_PROVIDERS` (Anthropic primero). Los precios de caché que falten siguen los multiplicadores de Anthropic
  (lectura 0,1 ×, escritura 5 min 1,25 ×, escritura 1 h 2 × la entrada).
- Al llegar una copia nueva, `Index.reprice` valora los mensajes que ya estaban sin precio.
- `/prices` dice de dónde sale el precio de cada modelo (`prices.json` o `models.dev`).
- `MODELS_DEV_URL` vacío desactiva la descarga.

## Consecuencias

- Un modelo nuevo tiene coste aproximado desde el día siguiente a su aparición en models.dev, sin tocar código.
- Primera petición de la pila fuera del equipo además del plugin de Grafana: solo un GET de un fichero
  público, sin enviar datos. Se documenta en el README y se puede desactivar.
- Los mensajes valorados después de leídos pierden los extras de uso (escrituras de 1 h, modo rápido, EE. UU.),
  que no se guardan en el índice: su coste es algo menor que el real en esos casos. Al reiniciar el colector
  se releen y se valoran con todos los extras.
- `tools/check_claude_prices.py` solo usa models.dev si encuentra la copia (`MODELS_DEV_FILE`).

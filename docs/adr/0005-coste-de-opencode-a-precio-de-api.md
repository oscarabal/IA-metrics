# ADR 0005: Coste de OpenCode a precio de API cuando OpenCode guarda 0

- **Estado:** aceptada
- **Fecha:** 2026-11-20

## Contexto

El colector de OpenCode leía el coste que OpenCode guarda en cada mensaje (`$.cost` en `opencode.db`).
OpenCode lo calcula con los precios de su caché de models.dev (`models.json`), y guarda 0 cuando el
proveedor no cobra por token (GitHub Copilot, un proveedor de empresa con tarifa plana) o cuando no conoce
el modelo. En la primera puesta en marcha, 17 modelos tenían mensajes con tokens y coste 0: el dashboard de
OpenCode infravaloraba el uso, y no era comparable con el de Claude Code, que siempre muestra el coste a
precio de API (telemetría o `prices.json`, ADR 0002) aunque se pague con suscripción.

## Opciones consideradas

1. **Dejar el coste que guarda OpenCode** y avisar de los modelos con coste 0.
2. **Marcar proveedores de suscripción** como «coste 0 correcto» (`OPENCODE_SUBSCRIPTION_PROVIDERS`) y no avisar de ellos.
3. **Valorar a precio de API los mensajes que OpenCode guarda con coste 0**, con los precios de `models.json`.
4. **Tabla de precios propia para OpenCode**, como `prices.json` en Claude Code.

## Decisión

Opción 3, en un único punto (`collectors/opencode/api_prices.py`, función `hybrid`):

- Un mensaje con coste mayor que 0 conserva el de OpenCode (`cost_source = tool`).
- Uno con tokens y coste 0 se valora con tokens × precio (`cost_source = computed`). El precio es el del
  propio proveedor en `models.json` si es mayor que 0; si no (Copilot no publica precios), el del fabricante
  del modelo, buscado por nombre sin distinguir puntos, guiones ni mayúsculas
  (`github-copilot/claude-opus-4.6` → `anthropic/claude-opus-4-6`), en el orden de `REFERENCE`.
- Los proveedores locales (LM Studio, Ollama…) cuestan 0.
- Sin precio en ningún sitio, el mensaje queda en 0 con `cost_source = missing`, y el panel «Modelos sin
  precio» y `/prices/missing` lo avisan.

`OPENCODE_SUBSCRIPTION_PROVIDERS` (opción 2) se conserva solo como etiqueta informativa en `/prices`.

## Consecuencias

- El coste de OpenCode en `/data`, los dashboards y el Resumen IA significa lo mismo que el de Claude Code:
  lo que costaría por API. Con suscripción no es lo que se paga (README, «Limitaciones»).
- Sin tabla que mantener: los precios llegan con la caché de models.dev de OpenCode. A cambio, un modelo que
  models.dev no conoce, o con un nombre que no coincide con el del fabricante, queda sin precio y hay que
  añadir una equivalencia.
- El coste que guardó OpenCode sigue disponible (`cost_tool` en `/data/usage`, columna «Coste OpenCode» en `/prices`).
- Pendiente: el informe de mejoras de OpenCode (`coach/report.py`) aún suma el coste que guarda OpenCode.
- Las series antiguas de Prometheus (`opencode_cost_usd_total`) siguen con el coste guardado; ningún panel de
  coste las usa.

## Alternativas descartadas

- **Opción 1:** el gasto de Copilot y del proveedor de empresa no aparecía en ningún panel.
- **Opción 2:** quitaba la alarma, pero seguía sin mostrar cuánto uso había detrás de esas suscripciones.
- **Opción 4:** duplicaría el trabajo de models.dev y exigiría mantener cientos de modelos a mano.

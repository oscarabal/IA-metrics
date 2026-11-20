# ADR 0001: Una sola pila Docker Compose con perfiles por herramienta

- **Estado:** aceptada
- **Fecha:** 2026-11-20

## Contexto

Existían dos proyectos separados, `claude-metrics` (Claude Code) y `opencode-metrics` (OpenCode), con
la misma finalidad: medir uso y coste. Ambos eran pilas Docker Compose con su propio Prometheus y Grafana
(puertos 3000 y 3001), código Python sin dependencias y mucho duplicado (página del informe, páginas de
sesión, reglas D1–D10 mantenidas por convención). No había forma de ver el gasto total en IA, y el
usuario debía poder elegir qué herramienta medir.

Diferencias que hay que conservar: Claude Code necesita OTel Collector y Loki para su telemetría y lee
sus ficheros de conversación; OpenCode solo necesita leer su base de datos SQLite.

## Opciones consideradas

1. **Docker Compose con perfiles** (`claude`, `opencode`) y Prometheus/Grafana comunes.
2. **Servicio nativo de Windows** (NSSM/WinSW) con Prometheus, Grafana, Loki y el collector como binarios.
3. **Aplicación propia** que sustituya a Grafana.

## Decisión

Opción 1. Un repositorio con:

- `docker-compose.yml` con perfiles; el perfil activo se guarda en `COMPOSE_PROFILES` (`.env`).
- Un Prometheus (365 días) y un Grafana compartidos, con un dashboard global además de los dos existentes.
- Dos colectores con la misma imagen y el mismo árbol de código (`collectors/`), con lo común en
  `collectors/common/`.
- Un instalador PowerShell (`Instalar.bat`) que elige perfiles, genera `.env`, configura la telemetría de
  Claude Code con confirmación y copia de seguridad, migra los volúmenes de las pilas antiguas y arranca.
- Las prácticas seguras de `opencode-metrics` como base: imágenes con versión fija, puertos solo en
  `127.0.0.1`, contraseña en `.env`.

## Consecuencias

- Se reutiliza casi todo el trabajo existente y Docker sigue siendo el único requisito.
- Los uids de datasource del informe pasan a ser `coach-claude` y `coach-opencode`, y los servicios se
  llaman `claude-collector` y `opencode-collector`; los dashboards se han ajustado.
- Los puertos de las páginas de sesión se mantienen (9100 y 9101), así que los enlaces siguen valiendo.
- El historial de Claude Code de la pila antigua se migra copiando volúmenes; el de OpenCode se reconstruye
  desde `opencode.db`.
- Docker Desktop requiere licencia de pago en empresas grandes; la alternativa prevista es Rancher Desktop
  o Podman con el mismo compose. La opción 2 solo se reconsiderará si Docker no es viable.
- La normalización del coste para el dashboard global se hace en las consultas de Grafana, no con
  recording rules: las series de Claude Code son por sesión y caducan a las 24 h, así que una suma
  registrada no sería monótona.

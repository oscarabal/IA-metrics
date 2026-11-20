# ADR 0004: Estrategia de pruebas automáticas

- **Estado:** aceptada
- **Fecha:** 2026-11-20

## Contexto

No hay pruebas. Un cambio de formato en Claude Code (ficheros de conversación, nombres de métricas o
eventos) o en el esquema de `opencode.db` solo se detecta mirando el dashboard. El informe de mejoras de
ambas herramientas comparte un contrato (reglas D1–D10, `FORMAT_VERSION`) mantenido a mano, y las reglas
están duplicadas con los mismos umbrales.

## Propuesta

Pruebas con la librería estándar (`unittest`), para no añadir dependencias a los colectores:

1. **Fixtures:** carpeta de conversaciones de Claude Code y un `opencode.db` mínimo, generados por un
   script, con casos conocidos (subagentes, worktrees, errores de herramientas, comandos y skills).
2. **Colectores:** `/metrics` con valores esperados, páginas de sesión, informe Markdown y JSON, y la
   comprobación de `Host`.
3. **Contrato del informe:** la salida JSON de ambos colectores cumple el mismo esquema (claves, ids de
   regla, `FORMAT_VERSION`).
4. **Configuración:** `promtool check config`, `docker compose config` con cada perfil, JSON válido de
   dashboards y que todo uid de datasource usado exista en `config/grafana/datasources.yaml`.
5. **Instalador:** análisis sintáctico con el parser de PowerShell y pruebas de `Set-EnvValue` y de la
   edición de `settings.json` sobre un HOME temporal.
6. **CI:** GitHub Actions ejecuta todo en cada push.

Esta suite es el requisito previo para unificar las reglas D1–D10 y las páginas de sesión en
`collectors/common/` (pendiente del ADR 0001) y para el ADR 0002.

## Consecuencias

- Los cambios de formato de las herramientas medidas se detectan al actualizar las fixtures.
- El refactor del código común se puede hacer con red de seguridad.
- Coste: mantener las fixtures cuando las herramientas cambien de formato.

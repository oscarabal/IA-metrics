---
title: Solution Strategy
arc42-section: "04"
description: Enfoques de fondo con los que IA-metrics cumple sus objetivos.
---

# Estrategia de solución

| Objetivo | Estrategia | Vista o ADR |
| --- | --- | --- |
| Elegir herramienta sin dos pilas | Un Docker Compose con perfiles `claude` y `opencode`; Prometheus y Grafana comunes | [ADR 0001](../adr/0001-pila-unica-docker-compose-con-perfiles.md), [07](07-deployment-view.md) |
| Cualquier rango de fechas sin explotar Prometheus | Registro por petición en cada colector y API JSON `/data` que Grafana lee con Infinity; Prometheus solo para estado actual | [ADR 0002](../adr/0002-registro-por-peticion-y-api-de-datos.md), [05](05-building-block-view.md) |
| Coste exacto y comparable entre herramientas | Coste híbrido con origen explícito (`cost_source`): telemetría o tabla de precios en Claude Code, coste guardado o precio de API en OpenCode | [ADR 0002](../adr/0002-registro-por-peticion-y-api-de-datos.md), [ADR 0005](../adr/0005-coste-de-opencode-a-precio-de-api.md), [08](08-crosscutting-concepts.md#coste-híbrido) |
| Historial aunque Claude Code borre conversaciones | Archivo de sesiones sin texto en `coach.db` | [ADR 0002](../adr/0002-registro-por-peticion-y-api-de-datos.md), [08](08-crosscutting-concepts.md#privacidad-solo-metadatos) |
| Privacidad | Solo metadatos; montajes de solo lectura; el texto de prompts solo en memoria y enmascarable | [08](08-crosscutting-concepts.md#privacidad-solo-metadatos) |
| Respuesta rápida con bind mounts lentos | Lectura en hilos de fondo y cachés; las peticiones HTTP solo copian lo calculado | [08](08-crosscutting-concepts.md#trabajo-en-segundo-plano) |
| Un solo código para dos colectores | Misma imagen, `collectors/` montado en `/srv`, lo común en `collectors/common/` | [05](05-building-block-view.md) |
| Cambios seguros | Tests con datos de ejemplo de ambas herramientas y de cada URL de cada dashboard | [ADR 0004](../adr/0004-estrategia-de-pruebas.md), [10](10-quality-requirements.md) |

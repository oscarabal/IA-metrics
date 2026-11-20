---
title: Architecture Decisions
arc42-section: "09"
description: Índice de las decisiones de arquitectura de IA-metrics y las vistas a las que afectan.
---

# Decisiones de arquitectura

Los motivos, alternativas y consecuencias están en cada ADR ([índice](../adr/README.md)).

| Decisión | ADR | Vistas afectadas |
| --- | --- | --- |
| Una sola pila Docker Compose con perfiles por herramienta | [0001](../adr/0001-pila-unica-docker-compose-con-perfiles.md) | [04](04-solution-strategy.md), [05](05-building-block-view.md), [07](07-deployment-view.md) |
| Registro por petición en cada colector y API JSON `/data` para Grafana; series por día retiradas | [0002](../adr/0002-registro-por-peticion-y-api-de-datos.md) | [04](04-solution-strategy.md), [05](05-building-block-view.md), [06](06-runtime-view.md), [08](08-crosscutting-concepts.md) |
| Estrategia de pruebas automáticas | [0004](../adr/0004-estrategia-de-pruebas.md) | [10](10-quality-requirements.md) |
| Coste de OpenCode a precio de API cuando OpenCode guarda 0 | [0005](../adr/0005-coste-de-opencode-a-precio-de-api.md) | [05](05-building-block-view.md), [06](06-runtime-view.md), [08](08-crosscutting-concepts.md) |

Decisiones tomadas sin ADR propio, registradas en `CLAUDE.md` y en la auditoría de seguridad del
20-11-2026: no publicar Prometheus ni Loki, healthchecks con `/health`, y no persistir el índice de Claude
Code por privacidad.

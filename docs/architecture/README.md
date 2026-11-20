---
title: Documentación de arquitectura
description: Índice de la documentación arc42 de IA-metrics.
---

# Documentación de arquitectura

Cómo está construida IA-metrics, la pila local que mide uso y coste de Claude Code y OpenCode. Qué hace y
cómo se usa está en el [README](../../README.md); las decisiones, en [docs/adr](../adr/README.md).

| Sección | Contenido |
| --- | --- |
| [01 Introducción y objetivos](01-introduction-and-goals.md) | Para qué existe y qué calidades la guían |
| [02 Restricciones](02-constraints.md) | Lo que limita las decisiones |
| [03 Contexto y alcance](03-context-and-scope.md) | Frontera del sistema y sistemas vecinos |
| [04 Estrategia de solución](04-solution-strategy.md) | Enfoques de fondo |
| [05 Vista de bloques](05-building-block-view.md) | Servicios, colectores y módulos |
| [06 Vista de ejecución](06-runtime-view.md) | Escenarios: una petición, el coste, el arranque |
| [07 Vista de despliegue](07-deployment-view.md) | Contenedores, volúmenes y puertos |
| [08 Conceptos transversales](08-crosscutting-concepts.md) | Privacidad, coste, seguridad, trabajo en segundo plano |
| [09 Decisiones](09-architecture-decisions.md) | Índice de los ADR |
| [10 Requisitos de calidad](10-quality-requirements.md) | Cómo se realizan y con qué pruebas |
| [11 Riesgos y deuda técnica](11-risks-and-technical-debt.md) | Lo que puede fallar y lo pendiente |
| [12 Glosario](12-glossary.md) | Términos |

No existe una fuente de intención de producto aparte (ProductShape u otra): lo que aquí depende de la
intención del producto se apoya en el README y en las decisiones de los ADR, y se indica como tal.

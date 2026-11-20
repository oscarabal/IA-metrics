---
title: Introduction and Goals
arc42-section: "01"
description: Para qué existe IA-metrics, sus calidades prioritarias y quién usa esta documentación.
---

# Introducción y objetivos

## Visión general de requisitos

IA-metrics responde a «cuánto uso Claude Code y OpenCode y cuánto cuesta», en el equipo de quien los usa y
sin enviar datos fuera. Sustituye a dos proyectos separados (`claude-metrics` y `opencode-metrics`) por una
pila con perfiles, un instalador que elige herramienta y un resumen común
([ADR 0001](../adr/0001-pila-unica-docker-compose-con-perfiles.md)). No hay una fuente de intención de
producto formal: el alcance está descrito en el [README](../../README.md).

## Objetivos de calidad

| Prioridad | Calidad | Qué significa aquí |
| --- | --- | --- |
| 1 | Privacidad | Nunca se guarda en disco texto de conversaciones, prompts ni errores ([08](08-crosscutting-concepts.md#privacidad-solo-metadatos)) |
| 2 | Exactitud del coste | Cada coste dice de dónde sale y coincide con la fuente ([08](08-crosscutting-concepts.md#coste-híbrido)) |
| 3 | Seguridad local | Nada accesible desde la red ni desde páginas web ([08](08-crosscutting-concepts.md#seguridad-de-red-local)) |
| 4 | Instalación sencilla | Docker como único requisito; un instalador para Windows |
| 5 | Mantenibilidad | Sin dependencias en los colectores; tests de cada URL de cada dashboard |

## Partes interesadas

| Quién | Qué busca en esta documentación |
| --- | --- |
| Quien mantiene el repositorio | Dónde va cada cambio y qué invariantes no romper |
| Agentes de código (Claude Code, OpenCode) | Estructura y convenciones antes de editar (`CLAUDE.md` resume las reglas) |
| Quien revisa la seguridad | Fronteras de confianza y flujo de datos sensibles |

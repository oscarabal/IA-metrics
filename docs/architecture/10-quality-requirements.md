---
title: Quality Requirements
arc42-section: "10"
description: Cómo realiza la arquitectura las calidades de IA-metrics y con qué evidencia.
---

# Requisitos de calidad

## Visión general

No hay requisitos de calidad formales (no existe una fuente de intención de producto con identificadores
QR). La tabla parte de los objetivos de [01](01-introduction-and-goals.md#objetivos-de-calidad), que se
apoyan en el README.

| Calidad | Realización | Evidencia o hueco |
| --- | --- | --- |
| Privacidad | Solo metadatos en disco; prompts en memoria y enmascarables ([08](08-crosscutting-concepts.md#privacidad-solo-metadatos)) | Tests de archivo y prompts. Hueco: los títulos de sesión van en etiquetas de Prometheus (auditoría #4) |
| Exactitud del coste | Coste híbrido con origen ([08](08-crosscutting-concepts.md#coste-híbrido)) | 0,0 % de desviación de `prices.json` frente a la telemetría ([ADR 0002](../adr/0002-registro-por-peticion-y-api-de-datos.md)); tests de equivalencia con `tests/legacy_oracle.py` |
| Seguridad local | Puertos mínimos en `127.0.0.1`, comprobación de `Host` ([08](08-crosscutting-concepts.md#seguridad-de-red-local)) | `test_config.py`; auditoría del 20-11-2026 sin hallazgos altos |
| Instalación sencilla | Docker y Python 3; instalador multiplataforma; `up -d --wait` | Funciones del instalador probadas en `tests/test_installer.py`; sin prueba de extremo a extremo en cada SO |
| Mantenibilidad | Sin dependencias; código común; tests de cada URL de cada dashboard | `python tests/run.py` y CI en cada push |
| Rendimiento | Lecturas en segundo plano ([08](08-crosscutting-concepts.md#trabajo-en-segundo-plano)) | `test_scrape_reads_no_database`; `opencode_series_read_seconds` en Prometheus |

## Escenarios de calidad

### Una web maliciosa intenta leer los datos

Una página abierta en el navegador hace que su dominio resuelva a `127.0.0.1` (DNS rebinding). El colector
recibe su nombre en `Host` y responde 421; Prometheus y Loki no están publicados.

### Claude Code borra conversaciones antiguas

Con la pila parada más de `cleanupPeriodDays`, los ficheros desaparecen. Al arrancar, `coach.db` restaura
las sesiones archivadas sin texto y su uso sigue contando (`test_usage_survives_deleted_conversations`).

### Aparece un modelo nuevo

Un modelo sin precio queda con coste `missing`, el panel «Modelos sin precio» se pone en rojo e
`Iniciar-metricas.bat` lo avisa; `/prices` dice cuál y de dónde saldría su precio.

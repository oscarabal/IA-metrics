---
title: Deployment View
arc42-section: "07"
description: Contenedores, volúmenes, montajes y puertos de IA-metrics en el equipo de la persona usuaria.
---

# Vista de despliegue

## Infraestructura nivel 1

### Visión general

Un solo equipo con Docker. `docker-compose.yml` define seis servicios en una red interna; `COMPOSE_PROFILES`
en `.env` decide cuáles arrancan.

| Servicio | Imagen | Perfil | Puerto publicado (`127.0.0.1`) | Volumen | Salud |
| --- | --- | --- | --- | --- | --- |
| prometheus | `prom/prometheus:v3.5.0` | siempre | — | `prometheus-data` (365 días) | `/-/ready` |
| grafana | `grafana/grafana:13.2.4` | siempre | 3000 | `grafana-data` | `/api/health` |
| otel-collector | `otel/opentelemetry-collector-contrib:0.130.0` | claude | 4317 | — | — |
| loki | `grafana/loki:3.4.2` | claude | — | `loki-data` (30 días) | — |
| claude-collector | `python:3.13-alpine` | claude | 9100 | `coach-data` | `/health` |
| opencode-collector | `python:3.13-alpine` | opencode | 9101 | — | `/health` |

### Motivo de la topología

- Docker Compose y perfiles: [ADR 0001](../adr/0001-pila-unica-docker-compose-con-perfiles.md).
- Prometheus, Loki y los puertos 4318/8889 no se publican: no tienen autenticación ni comprueban `Host`.
  `docker-compose.debug.yml` los publica en `127.0.0.1` mientras se depura.
- Los colectores no tienen imagen propia: montan `collectors/` en `/srv` (solo lectura) con
  `PYTHONPATH=/srv`; un cambio de código se aplica reiniciando el contenedor.

### Calidad y rendimiento

- Los montajes de Windows son lentos; por eso los colectores leen en hilos de fondo y Prometheus lee
  OpenCode cada 30 s con 25 s de margen.
- Logs de Docker limitados a 10 MB × 3 por servicio (`x-logging`).

### Correspondencia de bloques

| Bloque o artefacto | Elemento de infraestructura | Entorno |
| --- | --- | --- |
| `collectors/claude/` | Contenedor `claude-collector` | Docker local |
| `collectors/opencode/` | Contenedor `opencode-collector` | Docker local |
| `grafana/dashboards/` | Montaje de solo lectura en Grafana (provisionado) | Docker local |
| `coach.db` | Volumen `coach-data` | Docker local |
| `installer/install.ps1` | PowerShell 5.1 en el equipo | Windows |

## Infraestructura nivel 2

### Montajes de los colectores

| Colector | Origen en el equipo | Destino | Modo |
| --- | --- | --- | --- |
| claude-collector | `~/.claude/projects` | `/projects` | solo lectura |
| claude-collector | `~/.claude/commands`, `~/.claude/skills` | `/claude-config/*` | solo lectura |
| opencode-collector | `~/.local/share/opencode` | `/data` | solo lectura |
| opencode-collector | `~/.cache/opencode` | `/cache` | solo lectura |
| opencode-collector | `~/.config/opencode/commands` | `/commands` | solo lectura |

`~/.claude` nunca se monta entero ni `settings.json`; la carpeta de OpenCode incluye `auth.json`, que el
colector no abre ([11](11-risks-and-technical-debt.md)).

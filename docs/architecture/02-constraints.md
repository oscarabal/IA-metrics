---
title: Architecture Constraints
arc42-section: "02"
description: Restricciones técnicas y organizativas que limitan las decisiones de IA-metrics.
---

# Restricciones de arquitectura

| Restricción | Origen | Consecuencia en la arquitectura | Negociable |
| --- | --- | --- | --- |
| Todo en local, en un PC de un solo usuario | Privacidad de las conversaciones | Sin servicios en la nube, sin autenticación entre servicios, puertos en `127.0.0.1`. Las únicas peticiones salientes descargan ficheros públicos (plugin Infinity, catálogo de models.dev) y no envían datos; models.dev se desactiva con `MODELS_DEV_URL=` | No |
| Docker (Docker Desktop en Windows) como único requisito | Instalación sencilla ([ADR 0001](../adr/0001-pila-unica-docker-compose-con-perfiles.md)) | Docker Compose con perfiles; nada se instala en el sistema | Poco |
| Windows como plataforma principal | Usuarios actuales | Instalador PowerShell 5.1 con CRLF y BOM; rutas `${USERPROFILE}`; bind mounts lentos que obligan a leer en segundo plano | Sí (el compose funciona en macOS y Linux) |
| Solo la librería estándar de Python | Imagen `python:3.13-alpine` sin build ni gestor de paquetes | Servidores HTTP, SQLite y JSON propios; nada de frameworks | Sí |
| Lectura, nunca escritura, de los datos de las herramientas | No interferir con Claude Code ni OpenCode | Montajes `:ro`; `opencode.db` con `mode=ro` o `immutable=1` | No |
| Formatos ajenos sin contrato | Las conversaciones de Claude Code y el esquema de `opencode.db` pueden cambiar | Lectura tolerante a campos ausentes; tests con datos de ejemplo ([ADR 0004](../adr/0004-estrategia-de-pruebas.md)) | No |
| Grafana como interfaz | Reutilizar los dashboards existentes | Dashboards provisionados desde JSON; datasource Infinity para leer los colectores | Poco |

#!/usr/bin/env bash
# Instala o reconfigura IA-metrics (elige Claude Code, OpenCode o ambos). Con Python 3 usa installer/install.py; sin él, un contenedor (ADR 0009).
exec bash "$(dirname "$0")/installer/run.sh" install "$@"

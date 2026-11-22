#!/usr/bin/env bash
# Actualiza IA-metrics y conserva el historial. Con Python 3 usa installer/install.py; sin él, un contenedor (ADR 0009).
exec bash "$(dirname "$0")/installer/run.sh" update "$@"

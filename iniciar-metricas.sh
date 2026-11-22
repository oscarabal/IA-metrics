#!/usr/bin/env bash
# Arranca IA-metrics y abre Grafana. Con Python 3 usa installer/install.py; sin él, un contenedor (ADR 0009).
exec bash "$(dirname "$0")/installer/run.sh" start "$@"

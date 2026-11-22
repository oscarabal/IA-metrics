#!/usr/bin/env bash
# Desinstala IA-metrics. Con Python 3 usa installer/install.py; sin él, un contenedor (ADR 0009).
exec bash "$(dirname "$0")/installer/run.sh" uninstall "$@"

#!/usr/bin/env bash
# Arranca IA-metrics y abre Grafana.
cd "$(dirname "$0")"
exec python3 installer/install.py --start "$@"

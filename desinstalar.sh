#!/usr/bin/env bash
# Desinstala IA-metrics.
cd "$(dirname "$0")"
exec python3 installer/install.py --uninstall "$@"

#!/usr/bin/env bash
# Actualiza IA-metrics y conserva el historial.
cd "$(dirname "$0")"
exec python3 installer/install.py --update "$@"

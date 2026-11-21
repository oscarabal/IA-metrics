#!/usr/bin/env bash
# Instala o reconfigura IA-metrics (elige Claude Code, OpenCode o ambos).
cd "$(dirname "$0")"
exec python3 installer/install.py "$@"

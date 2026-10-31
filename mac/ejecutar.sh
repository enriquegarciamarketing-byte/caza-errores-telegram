#!/bin/bash
# Lo lanza launchd cada 15 minutos. Trae la última versión del bot y hace una pasada.
cd "$HOME/CazaChollos" || exit 1
git pull --ff-only -q 2>/dev/null || true
exec .venv/bin/python canal_amazon.py

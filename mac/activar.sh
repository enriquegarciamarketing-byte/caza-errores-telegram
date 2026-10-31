#!/bin/bash
# Activa la publicación automática en @cazachollos_com cada 15 minutos (de 08:00 a 01:00).
set -euo pipefail
DIR="$HOME/CazaChollos"
PLIST="$HOME/Library/LaunchAgents/com.cazachollos.canal.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$DIR/state"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cazachollos.canal</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/mac/ejecutar.sh</string></array>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/state/launchd.log</string>
  <key>StandardErrorPath</key><string>$DIR/state/launchd.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/com.cazachollos.canal" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Activado. Publica como máximo 3 por hora y 30 al día, de 08:00 a 01:00, con el Mac encendido."
echo "Registro: $DIR/state/canal_amazon.log    Para pararlo: bash $DIR/mac/pausar.sh"

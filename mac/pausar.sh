#!/bin/bash
launchctl bootout "gui/$(id -u)/com.cazachollos.canal" 2>/dev/null && echo "Canal pausado." || echo "Ya estaba pausado."

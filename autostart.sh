#!/bin/bash
#
# Pusha Talk - Autostart Configuration
#
# Usage:
#   ./autostart.sh enable   - Enable launch at login
#   ./autostart.sh disable  - Disable launch at login
#   ./autostart.sh status   - Check current status
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_NAME="com.pushatalk.plist"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"

case "${1:-}" in
    enable)
        echo "Enabling Pusha Talk autostart..."

        # Create LaunchAgents directory if needed
        mkdir -p "$HOME/Library/LaunchAgents"

        # Copy and customize plist
        sed "s|INSTALL_PATH|$SCRIPT_DIR|g" "$PLIST_SRC" > "$PLIST_DST"

        # Load the agent
        launchctl load "$PLIST_DST" 2>/dev/null || true

        echo "Done! Pusha Talk will now start at login."
        ;;

    disable)
        echo "Disabling Pusha Talk autostart..."

        # Unload the agent
        launchctl unload "$PLIST_DST" 2>/dev/null || true

        # Remove the plist
        rm -f "$PLIST_DST"

        echo "Done! Pusha Talk will no longer start at login."
        ;;

    status)
        if [ -f "$PLIST_DST" ]; then
            echo "Autostart: ENABLED"
            if launchctl list | grep -q "com.pushatalk"; then
                echo "Status: Running"
            else
                echo "Status: Not running"
            fi
        else
            echo "Autostart: DISABLED"
        fi
        ;;

    *)
        echo "Usage: $0 {enable|disable|status}"
        exit 1
        ;;
esac

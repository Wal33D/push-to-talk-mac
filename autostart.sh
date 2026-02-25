#!/bin/bash
#
# Dictator - Autostart Configuration
#
# Usage:
#   ./autostart.sh enable   - Enable launch at login
#   ./autostart.sh disable  - Disable launch at login
#   ./autostart.sh status   - Check current status
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_NAME="com.dictator.plist"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"

case "${1:-}" in
    enable)
        echo "Enabling Dictator autostart..."

        # Create LaunchAgents directory if needed
        mkdir -p "$HOME/Library/LaunchAgents"

        # Copy and customize plist
        sed "s|INSTALL_PATH|$SCRIPT_DIR|g" "$PLIST_SRC" > "$PLIST_DST"

        # Load the agent
        launchctl load "$PLIST_DST" 2>/dev/null || true

        echo "Done! Dictator will now start at login."
        ;;

    disable)
        echo "Disabling Dictator autostart..."

        # Unload the agent
        launchctl unload "$PLIST_DST" 2>/dev/null || true

        # Remove the plist
        rm -f "$PLIST_DST"

        echo "Done! Dictator will no longer start at login."
        ;;

    status)
        if [ -f "$PLIST_DST" ]; then
            echo "Autostart: ENABLED"
            if launchctl list | grep -q "com.dictator"; then
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

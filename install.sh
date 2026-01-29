#!/bin/bash
#
# Voice to Claude - Installation Script
#
# This script installs all dependencies and sets up the app.
#

set -e

echo "========================================"
echo "  Voice to Claude - Installation"
echo "========================================"
echo

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Install portaudio (required for pyaudio)
echo "Installing portaudio..."
brew install portaudio 2>/dev/null || true

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install --user -r requirements.txt

# Add alias to shell config
SHELL_RC="$HOME/.zshrc"
if [[ "$SHELL" == *"bash"* ]]; then
    SHELL_RC="$HOME/.bashrc"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALIAS_LINE="alias voice=\"python3 ${SCRIPT_DIR}/voice_to_claude.py\""

if ! grep -q "alias voice=" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# Voice to Claude" >> "$SHELL_RC"
    echo "$ALIAS_LINE" >> "$SHELL_RC"
    echo "Added 'voice' alias to $SHELL_RC"
else
    echo "'voice' alias already exists in $SHELL_RC"
fi

echo
echo "========================================"
echo "  Installation Complete!"
echo "========================================"
echo
echo "To start Voice to Claude:"
echo "  1. Open a new terminal (or run: source $SHELL_RC)"
echo "  2. Run: voice"
echo
echo "The app will appear in your menu bar."
echo
echo "On first run, macOS will ask for:"
echo "  - Microphone access"
echo "  - Accessibility access (for paste)"
echo

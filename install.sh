#!/bin/bash
#
# Dictator v2.0.1 — Installation Script
#
# Creates a virtual environment, installs all dependencies,
# and sets up the `voice` command.
#

set -euo pipefail

echo "========================================"
echo "  Dictator v2.0.1 — Installer"
echo "========================================"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Check Apple Silicon ────────────────────────────────────────────────
ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
    echo "ERROR: Dictator requires Apple Silicon (M1/M2/M3/M4)."
    echo "       Detected architecture: $ARCH"
    exit 1
fi
echo "✓ Apple Silicon detected ($ARCH)"

# ── 2. Check Python 3.9+ ─────────────────────────────────────────────────
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Install from https://python.org"
    exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    echo "ERROR: Python 3.9+ required. Found Python $PY_VERSION"
    exit 1
fi
echo "✓ Python $PY_VERSION"

# ── 3. Check / install Homebrew ───────────────────────────────────────────
if ! command -v brew &> /dev/null; then
    echo "Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for this session
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi
echo "✓ Homebrew"

# ── 4. Install native dependencies ────────────────────────────────────────
if ! brew list portaudio &> /dev/null; then
    echo "Installing portaudio..."
    brew install portaudio
else
    echo "✓ portaudio already installed"
fi

if ! brew list ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
else
    echo "✓ ffmpeg already installed"
fi

# ── 5. Create virtual environment ────────────────────────────────────────
VENV="$SCRIPT_DIR/venv"
if [ -d "$VENV" ]; then
    echo "Removing existing virtual environment..."
    rm -rf "$VENV"
fi
echo "Creating virtual environment..."
python3 -m venv "$VENV"
echo "✓ Virtual environment created at ./venv/"

# ── 6. Install Python dependencies ───────────────────────────────────────
echo "Installing Python dependencies (this may take a minute)..."
"$VENV/bin/pip" install --upgrade pip > /dev/null
"$VENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
echo "✓ Dependencies installed"

# ── 7. Make launcher executable ──────────────────────────────────────────
chmod +x "$SCRIPT_DIR/voice"
echo "✓ Launcher script ready"

# ── 8. Add voice alias to shell config ───────────────────────────────────
SHELL_RC="$HOME/.zshrc"
SHELL_PATH="${SHELL:-}"
if [[ "$SHELL_PATH" == *"bash"* ]]; then
    SHELL_RC="$HOME/.bashrc"
fi

ALIAS_LINE="alias voice=\"$SCRIPT_DIR/voice\""
ALIAS_LINE_ESCAPED="$(printf '%s\n' "$ALIAS_LINE" | sed 's/[&~\\]/\\&/g')"

if ! grep -q "alias voice=" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# Dictator" >> "$SHELL_RC"
    echo "$ALIAS_LINE" >> "$SHELL_RC"
    echo "✓ Added 'voice' alias to $SHELL_RC"
else
    # Update existing alias to point to new launcher
    sed -i '' "s~^alias voice=.*~$ALIAS_LINE_ESCAPED~" "$SHELL_RC"
    echo "✓ Updated 'voice' alias in $SHELL_RC"
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo
echo "========================================"
echo "  Installation Complete!"
echo "========================================"
echo
echo "To start Dictator:"
echo "  1. Open a new terminal (or run: source $SHELL_RC)"
echo "  2. Run: voice"
echo "  3. Or run directly: $SCRIPT_DIR/voice"
echo
echo "Debug mode:"
echo "  voice --debug"
echo "  (logs written to ~/.config/dictator/debug.log)"
echo
echo "IMPORTANT — macOS permissions required:"
echo "  System Settings → Privacy & Security → Accessibility"
echo "    → Add Terminal (or your terminal app)"
echo "  System Settings → Privacy & Security → Microphone"
echo "    → Enable for Terminal (or your terminal app)"
echo
echo "On first run, the Whisper model (~150 MB) will be downloaded."
echo "Subsequent launches are instant."
echo

# Voice to Claude

A macOS menu bar app for hands-free voice dictation. Continuously listens for speech, transcribes using Whisper AI, and auto-pastes to the active window.

Perfect for dictating to Claude Code, ChatGPT, or any text input without touching the keyboard.

![Menu Bar](https://img.shields.io/badge/macOS-Menu%20Bar%20App-blue)
![Python](https://img.shields.io/badge/Python-3.9+-green)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-Optimized-red)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Menu Bar Integration** - Lives in your macOS menu bar, always accessible
- **Continuous Listening** - Speak naturally, auto-detects when you stop
- **Fast Transcription** - Uses Lightning Whisper MLX optimized for Apple Silicon
- **Multiple Output Modes**
  - Paste + Send (Cmd+V then Enter)
  - Paste Only (just Cmd+V)
  - Copy Only (clipboard only)
- **Adjustable Sensitivity** - Low/Medium/High presets for different noise levels
- **Hallucination Filtering** - Filters out Whisper junk from background noise
- **Persistent Settings** - Config saved between sessions
- **Sound Effects** - Audio feedback for state changes
- **Transcription History** - View and copy recent transcriptions
- **Session Statistics** - Track words and transcriptions
- **Launch at Login** - Optional auto-start

## Requirements

- macOS 12+ (Monterey or later)
- Apple Silicon Mac (M1/M2/M3/M4)
- Python 3.9+
- Microphone access permission
- Accessibility permission (for paste)

## Quick Start

### Option 1: Automated Install

```bash
git clone https://github.com/Wal33D/voice-to-claude.git
cd voice-to-claude
./install.sh
```

Then run:
```bash
voice
```

### Option 2: Manual Install

1. Install portaudio:
   ```bash
   brew install portaudio
   ```

2. Install Python dependencies:
   ```bash
   pip3 install -r requirements.txt
   ```

3. Run the app:
   ```bash
   python3 voice_to_claude.py
   ```

## Usage

### Menu Bar Icon States

| Icon | State | Description |
|------|-------|-------------|
| ⏳ | Loading | Loading Whisper model |
| 🎤 | Ready | Listening for speech |
| 👂 | Listening | Detecting voice activity |
| 🗣 | Speaking | Recording your speech |
| ⚙️ | Processing | Transcribing audio |
| 📤 | Sending | Pasting to window |
| ⏸ | Paused | Listening paused |
| ❌ | Error | Check console for details |

### Menu Options

Click the menu bar icon to access:

- **Pause/Resume** - Toggle listening on/off
- **Sensitivity** - Adjust for room noise
  - Low (noisy room)
  - Medium (default)
  - High (quiet room)
- **Output Mode**
  - Paste + Send - Paste and press Enter
  - Paste Only - Just paste, no Enter
  - Copy Only - Just copy to clipboard
- **Whisper Model**
  - Base (fast) - Quicker, less accurate
  - Small (accurate) - Slower, more accurate
- **Sound Effects** - Toggle audio feedback
- **Recent Transcriptions** - Click to copy
- **Session Stats** - Word and transcription count

## Configuration

Settings are stored in `~/.config/voice-to-claude/config.json`:

```json
{
  "model": "base",
  "speech_threshold": 1500,
  "silence_duration": 1.0,
  "auto_send": true,
  "sound_effects": true
}
```

### Speech Threshold Guide

| Environment | Recommended Threshold |
|-------------|----------------------|
| Quiet room | 800 |
| Normal room | 1500 |
| Noisy room | 2500 |

## Launch at Login

To start Voice to Claude automatically when you log in:

```bash
./autostart.sh enable
```

To disable:
```bash
./autostart.sh disable
```

Check status:
```bash
./autostart.sh status
```

## Troubleshooting

### "Stuck on Speaking"
Your background noise is triggering false speech detection.
- Click the menu bar icon
- Go to **Sensitivity**
- Select **Low (noisy room)**

### Transcriptions contain junk like "1.1.1.1..."
This is Whisper hallucination from ambient noise.
- The app filters most of this automatically
- Try lowering sensitivity if it persists
- Speak closer to the microphone

### No microphone access
1. Open **System Preferences** > **Privacy & Security** > **Microphone**
2. Enable access for Terminal (or Python)

### Paste not working
1. Open **System Preferences** > **Privacy & Security** > **Accessibility**
2. Enable access for Terminal (or Python)

### Model takes too long to load
- The first run downloads the model (~150MB for base)
- Subsequent runs use the cached model
- Try the "Base" model for faster loading

## Project Structure

```
voice-to-claude/
├── voice_to_claude.py   # Main application
├── requirements.txt     # Python dependencies
├── install.sh           # Installation script
├── autostart.sh         # Launch at login script
├── com.voicetoclaude.plist  # LaunchAgent template
├── README.md            # This file
└── LICENSE              # MIT License
```

## Tech Stack

- **[rumps](https://github.com/jaredks/rumps)** - macOS menu bar framework
- **[Lightning Whisper MLX](https://github.com/mustafaaljadery/lightning-whisper-mlx)** - 10x faster Whisper for Apple Silicon
- **[PyAudio](https://people.csail.mit.edu/pyaudio/)** - Audio input
- **[pyperclip](https://github.com/asweigart/pyperclip)** - Clipboard access

## Contributing

Contributions welcome! Please open an issue or PR.

## License

MIT License - See [LICENSE](LICENSE) for details.

## Changelog

### v1.1.0
- Added persistent configuration
- Added output mode selection (paste+send, paste only, copy only)
- Added sound effects with toggle
- Added transcription history
- Added session statistics
- Added Whisper model selection
- Added launch at login support
- Improved hallucination filtering
- Added installation script

### v1.0.0
- Initial release
- Basic voice-to-text with menu bar UI
- Adjustable sensitivity
- Auto-paste and send

---

Built for hands-free coding with [Claude Code](https://claude.ai/code).

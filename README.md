# Voice to Claude

**macOS push-to-talk voice dictation. Hold Fn to speak, release to paste. Free, local, open source.**

![macOS](https://img.shields.io/badge/macOS-12%2B-blue)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-Required-red)
![Python](https://img.shields.io/badge/Python-3.9+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Why Voice to Claude?

| | Voice to Claude | Whisper Flow |
|---|---|---|
| **Price** | Free forever | $8/mo after trial |
| **Processing** | 100% local on-device | Cloud-based |
| **Privacy** | Audio never leaves your Mac | Audio sent to servers |
| **Source** | Open source (MIT) | Proprietary |
| **Trial** | No trial — just works | 7-day trial, then paywall |
| **Engine** | Lightning Whisper MLX | Whisper (cloud) |

## Requirements

- macOS 12+ (Monterey or later)
- Apple Silicon Mac (M1/M2/M3/M4)
- Python 3.9+

## Quick Start

```bash
git clone https://github.com/Wal33D/push-to-talk-mac.git
cd push-to-talk-mac
./install.sh
voice
```

The installer handles everything: creates a virtual environment, installs dependencies, and sets up the `voice` command.

## How It Works

Voice to Claude uses **push-to-talk** (PTT). No always-on listening, no false triggers.

1. **Hold Fn (Globe)** — a floating HUD appears with green audio bars
2. **Speak** — the bars react to your voice in real time
3. **Release Fn** — pulsing dots appear while Whisper transcribes
4. **Text is pasted** into the active window automatically

The entire flow happens in under a second for short phrases.

## Menu Bar Icon States

| Icon | State | Description |
|------|-------|-------------|
| ⏳ | Loading | Downloading/loading Whisper model |
| 🎤 | Ready | Hold PTT key to speak |
| 🗣 | Recording | Capturing your speech |
| ⚙️ | Processing | Transcribing audio |
| 📤 | Sending | Pasting to active window |
| ⏸ | Paused | PTT disabled (click to resume) |
| ❌ | Error | Check debug log for details |

## Features

- **Push-to-Talk** — Hold Fn (Globe), Right/Left Option, Right Command, Right Shift, or F17-F19
- **Floating HUD** — Visual feedback with audio bars, processing dots
- **5 Output Modes** — Paste+Send, Paste Only, Type+Send, Type Only, Copy Only
- **Configurable Send Key** — Enter, Ctrl+Enter, Cmd+Enter, Shift+Enter
- **5 Whisper Models** — Tiny, Base, Small, Medium, Large (all local)
- **14 Languages** — English, Spanish, French, German, and more
- **Dictation Commands** — Say "period", "comma", "new line", etc.
- **Smart Text Processing** — Auto-capitalize, smart punctuation, filler word removal
- **Hallucination Filtering** — Filters Whisper junk from background noise
- **Input Device Selection** — Choose which microphone to use
- **Sound Effects** — Audio feedback for PTT press/release
- **Transcription History** — View, copy, and export recent transcriptions
- **Session & Lifetime Stats** — Track words and transcriptions
- **Launch at Login** — Optional auto-start via launchd
- **Append Mode** — Append to clipboard instead of replacing

## Dictation Commands

When enabled, you can speak these commands and they'll be replaced:

### Punctuation
| Say | Get |
|-----|-----|
| "period" / "full stop" | . |
| "comma" | , |
| "question mark" | ? |
| "exclamation mark" | ! |
| "colon" | : |
| "semicolon" | ; |
| "hyphen" | - |
| "dash" | - (spaced) |
| "open quote" / "close quote" | " |
| "open paren" / "close paren" | ( ) |
| "ellipsis" | ... |

### Whitespace
| Say | Get |
|-----|-----|
| "new line" / "newline" | (line break) |
| "new paragraph" | (double line break) |
| "tab" | (tab character) |

### Symbols
| Say | Get |
|-----|-----|
| "at sign" | @ |
| "hashtag" / "hash" | # |
| "ampersand" | & |
| "dollar sign" | $ |
| "percent" | % |
| "asterisk" | * |
| "slash" | / |
| "underscore" | _ |
| "arrow" | -> |
| "fat arrow" | => |

### Control Commands
| Say | Action |
|-----|--------|
| "scratch that" / "delete that" | Undo last paste (Cmd+Z) |
| "cancel that" / "never mind" | Discard transcription |
| "repeat that" | Re-paste last transcription |

**Example**: Say "Hello comma how are you question mark" to get "Hello, how are you?"

## Configuration

Settings are stored in `~/.config/voice-to-claude/config.json`:

```json
{
  "model": "base",
  "ptt_key": "fn",
  "auto_send": true,
  "output_mode": "paste_send",
  "sound_effects": true,
  "show_notifications": true,
  "dictation_commands": true,
  "auto_capitalize": true,
  "smart_punctuation": true,
  "send_key": "return",
  "append_mode": false
}
```

`output_mode` values: `paste_send`, `paste_only`, `type_send`, `type_only`, `copy_only`.

All settings can be changed from the menu bar — no need to edit the file directly.

## Troubleshooting

### Accessibility permission
The app needs Accessibility access to simulate Cmd+V paste and to detect the Fn key.

**System Settings → Privacy & Security → Accessibility → Add your terminal app**

If you see "Could not create event tap for Fn key" in the debug log, this permission is missing.

### Fn key not working
- Make sure Accessibility permission is granted (see above)
- If your Fn key is mapped to emoji picker, go to **System Settings → Keyboard** and set "Press fn key to" → "Do Nothing" or "Change Input Source"
- Try a different PTT key from the menu (e.g., Right Option)

### pyobjc import errors
If the HUD or Fn key detection doesn't work:
```bash
# Reinstall from scratch
rm -rf venv && ./install.sh
```
The `pyobjc-framework-Cocoa` and `pyobjc-framework-Quartz` packages must be installed — `install.sh` handles this automatically.

### ffmpeg not found
If transcriptions fail with `No such file or directory: 'ffmpeg'`:
```bash
brew install ffmpeg
```
Then restart the app. `install.sh` now installs `ffmpeg` automatically.

### First-run model download
The first time you launch, Whisper downloads the model (~150 MB for base). This is a one-time download — subsequent launches are instant. The loading icon (⏳) will show until it's ready.

### Debug mode
To see detailed logs:
```bash
voice --debug
```
Or set the environment variable:
```bash
VTC_DEBUG=1 voice
```
Logs are written to `~/.config/voice-to-claude/debug.log`.

### Microphone not detected
1. **System Settings → Privacy & Security → Microphone** → enable for your terminal
2. Use the **Test Microphone** option in the menu bar to verify levels
3. Try selecting a specific input device from the **Input Device** menu

## Launch at Login

```bash
./autostart.sh enable    # Enable auto-start
./autostart.sh disable   # Disable auto-start
./autostart.sh status    # Check status
```

## Changelog

### v2.0.1
- Fixed dictation command matching so words like "periodic" no longer get mutated by command replacement
- Fixed output-mode persistence/checkmarks for non-paste modes (Type+Send, Type Only, Copy Only)
- Hardened config writes and AppleScript escaping for notifications/text output
- Improved debug logging around clipboard, HUD, and subprocess failures
- Installer now ensures `ffmpeg` is installed (required by Lightning Whisper MLX)

### v2.0.0
- **Push-to-Talk** — Complete rewrite from continuous listening to PTT mode
- **Floating HUD** — Native macOS overlay with audio bars and processing animation
- **Fn (Globe) key support** — Quartz-based modifier flag detection
- **Multiple PTT keys** — Fn, Right Option, Right Command, Right Shift, F17-F19
- **Smart text processing** — Filler word removal, auto-capitalize, smart punctuation
- **Text corrections** — Automatic contraction fixes (dont → don't, im → I'm)
- **Control commands** — "scratch that", "cancel that", "repeat that"
- **Type output modes** — Type+Send and Type Only for paste-blocking apps
- **Append mode** — Append to clipboard instead of replacing
- **Venv-based install** — Clean isolated environment, no system Python conflicts
- **Debug logging opt-in** — No log file created unless `--debug` or `VTC_DEBUG=1`
- **Launcher script** — `./voice` activates venv automatically

### v1.8.1
- Improved hallucination filtering (fixed false positives for valid sentences)
- Enhanced filler word removal (um, uh, you know, I mean)
- Better handling of orphaned commas after filler removal
- Fixed word boundary matching for short patterns
- Added more text corrections for common contractions
- Smart question detection (auto-adds ? for questions)

### v1.8.0
- Added comprehensive filler word removal (like Wispr Flow)
- Added more text corrections for contractions
- Added double word removal (the the → the)
- Added more hallucination patterns (timestamps, music symbols)
- Improved sentence capitalization

### v1.7.0
- Added 5 Whisper model options (tiny, base, small, medium, large-v3)

### v1.6.1
- Added recording sound option

### v1.6.0
- Added smart punctuation (auto-period, capitalize after sentences)
- Added text corrections (i → I, i'm → I'm, etc.)
- Added "Undo Last" to copy original text back to clipboard

### v1.5.0
- Added pause duration control
- Auto-stops `say` command when user starts speaking

### v1.4.1
- Improved hallucination filtering
- Raised default speech threshold

### v1.4.0
- Added auto-capitalize, ready sound, customizable send key
- Added microphone test, quick help dialog

### v1.3.0
- Added dictation commands, notifications, export history

### v1.2.0
- Added microphone calibration, input device selection, recording timeouts
- Added About dialog, CONTRIBUTING.md

### v1.1.0
- Added persistent config, output modes, sound effects, transcription history
- Added session stats, model selection, launch at login, install script

### v1.0.0
- Initial release

## License

MIT License — See [LICENSE](LICENSE) for details.

---

Built for hands-free coding with [Claude Code](https://claude.ai/code).

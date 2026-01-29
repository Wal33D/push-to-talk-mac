# Voice to Claude

A macOS menu bar app for hands-free voice dictation. Continuously listens for speech, transcribes using Whisper AI, and auto-pastes to the active window.

Perfect for dictating to Claude Code, ChatGPT, or any text input without touching the keyboard.

![Menu Bar](https://img.shields.io/badge/macOS-Menu%20Bar%20App-blue)
![Python](https://img.shields.io/badge/Python-3.9+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Menu Bar Integration** - Lives in your macOS menu bar, always accessible
- **Continuous Listening** - Speaks naturally, auto-detects when you stop
- **Fast Transcription** - Uses Lightning Whisper MLX optimized for Apple Silicon
- **Auto-Paste & Send** - Transcribed text is pasted and sent automatically
- **Adjustable Sensitivity** - Low/Medium/High presets for different noise environments
- **Hallucination Filtering** - Filters out Whisper junk output from background noise

## Requirements

- macOS (uses native menu bar and AppleScript)
- Apple Silicon Mac (M1/M2/M3) for MLX acceleration
- Python 3.9+
- Microphone access permission

## Installation

### 1. Install system dependencies

```bash
brew install portaudio
```

### 2. Clone the repository

```bash
git clone https://github.com/YourUsername/voice-to-claude.git
cd voice-to-claude
```

### 3. Install Python dependencies

```bash
pip3 install -r requirements.txt
```

### 4. Grant permissions

On first run, macOS will ask for:
- **Microphone access** - Required for voice input
- **Accessibility access** - Required for simulating keyboard input (paste)

## Usage

### Run the app

```bash
python3 voice_to_claude.py
```

### Or create an alias

Add to your `~/.zshrc`:

```bash
alias voice="python3 ~/Documents/GitHub/voice-to-claude/voice_to_claude.py"
```

Then just run:

```bash
voice
```

### Menu Bar Controls

| Icon | State |
|------|-------|
| ⏳ | Loading model |
| 🎤 | Ready (listening) |
| 👂 | Listening for speech |
| 🗣 | Speaking detected |
| ⚙️ | Processing/transcribing |
| 📤 | Sending to active window |
| ⏸ | Paused |
| ❌ | Error |

Click the icon to access:
- **Pause/Resume** - Toggle listening
- **Sensitivity** - Adjust for room noise level
- **Auto-Send** - Toggle Enter key after paste
- **Quit** - Exit the app

## Configuration

Edit the `CONFIG` dict in `voice_to_claude.py`:

```python
CONFIG = {
    "model": "base",           # "base" (fast) or "small" (accurate)
    "speech_threshold": 1500,  # Mic sensitivity (higher = less sensitive)
    "silence_duration": 1.0,   # Seconds of silence before stopping
    "auto_send": True,         # Press Enter after paste
}
```

## How It Works

1. **Listens** continuously using PyAudio
2. **Detects speech** when audio level exceeds threshold
3. **Records** until silence is detected
4. **Transcribes** using Lightning Whisper MLX (10x faster than standard Whisper)
5. **Filters** hallucinations (junk output from noise)
6. **Pastes** via AppleScript (Cmd+V + Enter)
7. **Repeats** - goes back to listening

## Troubleshooting

### "Stuck on Speaking"
- Increase sensitivity threshold (use "Low" for noisy rooms)
- Background noise may be triggering false speech detection

### Junk output like "1.1.1.1..."
- This is Whisper hallucination from noise
- The app filters most of these automatically
- Try increasing sensitivity if it persists

### No microphone access
- Go to System Preferences > Security & Privacy > Privacy > Microphone
- Enable access for Terminal or your Python interpreter

### Paste not working
- Go to System Preferences > Security & Privacy > Privacy > Accessibility
- Enable access for Terminal or your Python interpreter

## Tech Stack

- **[rumps](https://github.com/jaredks/rumps)** - macOS menu bar framework
- **[Lightning Whisper MLX](https://github.com/mustafaaljadery/lightning-whisper-mlx)** - Fast Whisper for Apple Silicon
- **[PyAudio](https://people.csail.mit.edu/hubert/pyaudio/)** - Audio input
- **[pyperclip](https://github.com/asweigart/pyperclip)** - Clipboard access

## License

MIT License - See [LICENSE](LICENSE) for details.

## Author

Built for hands-free coding with Claude Code.

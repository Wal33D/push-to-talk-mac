# Contributing to Voice to Claude

Thank you for your interest in contributing! Here's how you can help.

## Reporting Issues

- Check existing issues first
- Include your macOS version
- Include Python version (`python3 --version`)
- Include any error messages from Terminal

## Feature Requests

- Open an issue with the `enhancement` label
- Describe the use case
- Explain why it would be useful

## Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Test thoroughly
5. Commit with clear messages
6. Push and open a PR

### Code Style

- Follow PEP 8
- Use type hints where possible
- Add docstrings to functions
- Keep functions small and focused

### Testing

Before submitting:
1. Run the app and test all menu options
2. Test with different sensitivity settings
3. Test pause/resume
4. Verify transcription quality

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/voice-to-claude.git
cd voice-to-claude

# Install dependencies
pip3 install -r requirements.txt

# Run in development
python3 voice_to_claude.py
```

## Ideas for Contributions

- [ ] Add more Whisper model options (tiny, medium, large)
- [ ] Add language selection
- [ ] Add global keyboard shortcut
- [ ] Add notification support
- [ ] Create a native macOS app bundle
- [ ] Add waveform visualization
- [ ] Add audio input device selection
- [ ] Add export transcription history

## Questions?

Open an issue with the `question` label.

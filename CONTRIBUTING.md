# Contributing to Voice to Claude

Thank you for your interest in contributing! Here's how you can help.

## Reporting Issues

- Check existing issues first
- Include your macOS version
- Include Python version (`python3 --version`)
- Include any error messages from the debug log (`voice --debug`)

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
1. Run `rm -rf venv && ./install.sh` to verify clean install
2. Run `voice` and test all menu options
3. Test PTT with Fn key and at least one other key
4. Test pause/resume
5. Test `voice --debug` and verify log output
6. Verify `./autostart.sh enable && ./autostart.sh status`

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/voice-to-claude.git
cd voice-to-claude

# Install into a virtual environment
./install.sh

# Run in development (with debug logging)
./voice --debug

# Or manually activate venv
source venv/bin/activate
python3 voice_to_claude.py --debug
```

## Ideas for Contributions

- [ ] Native macOS .app bundle (py2app or Platypus)
- [ ] Custom wake word as alternative to PTT
- [ ] Per-app output mode profiles (auto-switch based on frontmost app)
- [ ] Whisper model auto-download progress bar in HUD
- [ ] Multi-monitor HUD positioning

## Questions?

Open an issue with the `question` label.

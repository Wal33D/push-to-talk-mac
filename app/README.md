# App Package Scaffolding

This directory is the incremental migration target from the current monolithic
`voice_to_claude.py` implementation to a platform-adapter architecture.

Current status:
1. Base package structure is in place (`core`, `platform`, `stt`).
2. Shared interfaces are defined for UI, hotkeys, output automation, startup,
   and transcription backends.
3. `core` now owns configuration, state metadata, and dictation processing.
4. macOS output automation is extracted to `app/platform/macos/output.py`.
5. MLX transcription backend is extracted to `app/stt/mlx_backend.py`.
6. `TranscriptionEngine` is extracted to `app/core/transcription.py`.
7. `AudioEngine` is extracted to `app/core/audio.py`.
8. macOS hotkey/output protocol adapters are now available in
   `app/platform/macos/`.
9. macOS autostart manager wrapper exists in `app/platform/macos/autostart.py`.
10. Runtime wiring still lives in `voice_to_claude.py` until extraction tasks
    are migrated in small, testable slices.

Migration order:
1. Move platform-agnostic logic to `app/core`.
2. Implement macOS adapter wrappers in `app/platform/macos`.
3. Implement Windows adapters in `app/platform/windows`.
4. Switch entrypoint orchestration to use these interfaces.

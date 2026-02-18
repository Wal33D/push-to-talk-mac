# Windows Support Master Plan

Status: Draft v1  
Date: 2026-02-18  
Project: Voice to Claude (`push-to-talk-mac`)  
Primary Goal: Ship a stable Windows version without regressing macOS quality.

## 1. Executive Summary

This document is the execution blueprint to add Windows support for Voice to Claude.

The strategy is:
1. Extract platform-agnostic core logic from the current monolithic macOS script.
2. Add platform adapters (macOS + Windows) behind explicit interfaces.
3. Introduce a transcription backend abstraction because MLX is Apple-only.
4. Deliver a Windows MVP first, then close feature parity gaps.
5. Work in small increments with frequent commits, pushes, and macOS regression checks.

MVP target (Windows):
1. Global push-to-talk.
2. Accurate transcription.
3. Output modes: Paste+Send, Paste Only, Copy Only.
4. Tray menu + settings persistence.
5. Startup at login.
6. Installer + signed executable (if signing budget available).

## 2. Why This Matters

Windows support unlocks:
1. Larger user base.
2. Lower churn from mixed-device users (Mac + Windows).
3. Better product credibility (cross-platform support).

Constraints:
1. Current implementation is macOS-specific in UI, key detection, notifications, and text output automation.
2. Current transcription engine (`lightning-whisper-mlx`) is Apple Silicon/MLX specific.
3. Packaging and auto-start behavior differ significantly on Windows.

## 3. Current-State Assessment (as of 2026-02-18)

Current app entrypoint: `voice_to_claude.py`  
Approximate size: 2k+ lines, monolithic with mixed concerns.

Current platform-coupled areas:
1. Menu bar UI: `rumps` (macOS only).
2. HUD: AppKit/Quartz.
3. Fn key monitoring: Quartz event tap.
4. Output simulation: AppleScript (`osascript`).
5. Auto-start: launchd plist + `autostart.sh`.

Current cross-platform-capable areas:
1. Text processing (`DictationProcessor`) with minor cleanup needed.
2. Audio capture (`pyaudio`) with device selection.
3. Clipboard (`pyperclip`) in principle cross-platform.
4. History and stats data model.

Primary technical debt to address:
1. Core and platform logic are intertwined.
2. No explicit abstraction boundaries.
3. No automated test harness for transcription/text/output behavior.

## 4. Product Scope

### 4.1 Windows MVP (Phase 1)

Included:
1. Push-to-talk with configurable key (default: Right Alt).
2. Tray app with state icon and essential menu.
3. Transcription via non-MLX backend.
4. Core output modes:
   1. Paste + Send.
   2. Paste Only.
   3. Copy Only.
5. Persistent config and migration from defaults.
6. Basic debug logs.
7. Startup registration (Current user).
8. Installable artifact (`.exe` + setup).

Excluded from MVP:
1. Full visual HUD parity with macOS.
2. Fn-key semantics (Windows laptops vary; no direct equivalent expected).
3. Every advanced menu workflow from macOS.

### 4.2 Post-MVP Parity (Phase 2)

1. Type+Send and Type Only reliability across common apps.
2. Windows-native visual overlay/HUD.
3. Expanded tray settings UX.
4. More robust hotkey profiles and conflict resolution.
5. Better startup and update UX.

## 5. Technical Direction

## 5.1 Architecture Refactor Plan

Target architecture:

1. `core/`
   1. App state machine.
   2. Dictation/text processing.
   3. Config management.
   4. History/stats.
   5. Orchestration pipeline (record -> transcribe -> process -> output).
2. `platform/`
   1. `macos/` adapter.
   2. `windows/` adapter.
3. `stt/`
   1. `mlx_backend.py` (macOS).
   2. `faster_whisper_backend.py` (Windows + optional macOS fallback).

Critical interfaces (protocol-style):
1. `GlobalHotkeyProvider`
   1. `start()`, `stop()`, `set_key(key)`.
   2. Emits `on_press`, `on_release`.
2. `UiShell`
   1. `set_state(state)`, `show_notification(title, message)`, menu updates.
3. `OutputAutomation`
   1. `paste_and_send(text, send_key)`, `paste_only(text)`, `copy_only(text)`, `type_text(text)`.
4. `TranscriptionBackend`
   1. `load_model(model_name)`.
   2. `transcribe(audio_file, language=None)`.
5. `AutoStartManager`
   1. `enable()`, `disable()`, `status()`.

Success criterion:
1. `core` knows nothing about AppleScript, Quartz, Win32 APIs, or tray libraries.

## 5.2 Windows Stack Recommendation

1. UI tray:
   1. `pystray` for system tray and menu.
   2. Optional `Pillow` icon generation.
2. Hotkeys:
   1. `pynput` (already used) for global key events.
   2. Fallback adapter for edge cases if key hooks fail.
3. Output automation:
   1. Primary: Win32 `SendInput` wrapper.
   2. Fallback: `pyautogui` only if necessary (avoid if possible).
4. Notifications:
   1. `win10toast-click` or PowerShell toast wrapper.
5. Startup:
   1. Create/remove shortcut in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.
6. STT backend:
   1. `faster-whisper` on CPU for baseline.
   2. Optional CUDA profile later.

Rationale:
1. `faster-whisper` avoids MLX dependency.
2. Win32 `SendInput` gives predictable key simulation.
3. Startup shortcut is simple and admin-free.

## 5.3 Dependency Strategy

Split dependencies:
1. `requirements-common.txt`
2. `requirements-macos.txt`
3. `requirements-windows.txt`
4. Keep top-level `requirements.txt` for current behavior during transition, then deprecate.

Windows expected additions:
1. `faster-whisper`
2. `pystray`
3. `Pillow`
4. `pywin32` (if Win32 wrappers required)
5. `win10toast-click` (if selected for notifications)

## 5.4 File/Directory Target Layout

```text
.
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── app_controller.py
│   │   ├── config.py
│   │   ├── dictation.py
│   │   ├── models.py
│   │   └── history.py
│   ├── stt/
│   │   ├── base.py
│   │   ├── mlx_backend.py
│   │   └── faster_whisper_backend.py
│   └── platform/
│       ├── base.py
│       ├── macos/
│       │   ├── ui.py
│       │   ├── hotkey.py
│       │   ├── output.py
│       │   └── autostart.py
│       └── windows/
│           ├── ui.py
│           ├── hotkey.py
│           ├── output.py
│           └── autostart.py
├── scripts/
│   ├── install_macos.sh
│   ├── install_windows.ps1
│   ├── build_windows.ps1
│   └── smoke_test_windows.ps1
├── packaging/
│   ├── windows/
│   │   ├── pyinstaller.spec
│   │   └── installer.iss
│   └── macos/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── manual/
└── WINDOWS_SUPPORT_PLAN.md
```

## 6. Work Breakdown Structure (Epic -> Task)

Each item includes estimate and acceptance criteria.

## EPIC W1: Platform Abstraction (5-7 days)

### W1-T1: Introduce core interfaces
Estimate: 1 day  
Deliverable:
1. Base interfaces/protocols for UI, hotkey, output, transcription, autostart.
Acceptance:
1. Existing macOS app compiles and runs through interface wrappers.
2. No behavior change for macOS users.

### W1-T2: Extract dictation + config + history to core
Estimate: 1.5 days  
Deliverable:
1. `DictationProcessor`, config IO, history/stat logic moved to `core`.
Acceptance:
1. Existing features still behave identically.
2. Unit tests added for dictation and config migration.

### W1-T3: Extract orchestration pipeline
Estimate: 2 days  
Deliverable:
1. `AppController` coordinates states and delegates to adapters.
Acceptance:
1. macOS adapter works via controller.
2. State transitions preserved.

### W1-T4: Regression hardening
Estimate: 1-2 days  
Deliverable:
1. Smoke tests and baseline logs.
Acceptance:
1. No new macOS regressions in core flows.

## EPIC W2: STT Backend Abstraction (3-5 days)

### W2-T1: Define transcription backend interface
Estimate: 0.5 day  
Acceptance:
1. MLX backend complies with interface.

### W2-T2: Add `faster-whisper` backend
Estimate: 1.5-2 days  
Acceptance:
1. Transcribes test WAV on Windows dev VM.
2. Language hint support implemented.

### W2-T3: Model management and defaults
Estimate: 1 day  
Acceptance:
1. Windows defaults to model `base` CPU profile.
2. Config persists model selection.

### W2-T4: Error taxonomy
Estimate: 1 day  
Acceptance:
1. Missing model/download/decoder errors are user-readable.
2. Debug logs include stack traces.

## EPIC W3: Windows Platform Adapter (7-10 days)

### W3-T1: Tray UI shell
Estimate: 2 days  
Acceptance:
1. Tray icon states map to existing state machine.
2. Menu supports pause/resume, output mode, send key, model, language, exit.

### W3-T2: Global hotkey provider
Estimate: 2 days  
Acceptance:
1. Press-and-hold key path reliably starts/stops recording.
2. Hotkey is configurable and persisted.
3. Handles key bounce safely.

### W3-T3: Output automation provider
Estimate: 2 days  
Acceptance:
1. Paste+Send, Paste Only, Copy Only validated in:
   1. Notepad.
   2. VS Code.
   3. Browser text area.
2. Failure paths are logged and user-notified.

### W3-T4: Notifications and UX
Estimate: 1 day  
Acceptance:
1. Notifications can be toggled.
2. No crash on notification failure.

### W3-T5: Startup manager
Estimate: 1 day  
Acceptance:
1. Enable/disable/status works without admin.
2. Startup state reflected in menu.

## EPIC W4: Packaging and Distribution (4-6 days)

### W4-T1: Windows install script
Estimate: 1 day  
Acceptance:
1. `scripts/install_windows.ps1` sets up venv and installs requirements.

### W4-T2: PyInstaller build pipeline
Estimate: 1.5-2 days  
Acceptance:
1. Single distributable produced.
2. App launches on clean Windows VM.

### W4-T3: Installer wrapper
Estimate: 1-2 days  
Acceptance:
1. `exe` installer places app, shortcut, uninstall entry.

### W4-T4: Optional signing integration
Estimate: 0.5-1 day  
Acceptance:
1. Signing step pluggable in CI if cert is available.

## EPIC W5: QA, Docs, and Beta Rollout (4-6 days)

### W5-T1: Test matrix + scripted smoke tests
Estimate: 1-2 days  
Acceptance:
1. Standardized pass/fail checklist.

### W5-T2: Documentation
Estimate: 1 day  
Acceptance:
1. README gains Windows install/use/troubleshooting sections.
2. CONTRIBUTING includes Windows dev loop.

### W5-T3: Beta release process
Estimate: 1 day  
Acceptance:
1. Tagged beta artifact with release notes.
2. Feedback template prepared.

### W5-T4: Stabilization loop
Estimate: 1-2 days  
Acceptance:
1. Top P0/P1 bugs fixed.
2. Go/no-go decision recorded.

## 7. Milestones and Timeline

Assumption: 1 full-time engineer, occasional reviewer support.

1. Week 1:
   1. Complete EPIC W1.
   2. Start W2.
2. Week 2:
   1. Finish W2.
   2. Start W3 (tray + hotkeys).
3. Week 3:
   1. Finish W3.
   2. Start W4.
4. Week 4:
   1. Finish W4 + W5.
   2. Ship beta.

MVP beta target: end of week 4.  
Parity target: week 6+ depending on post-beta findings.

## 8. Execution Discipline (Commit/Push/Test Cadence)

These rules apply for the full project, not just release week.

### 8.1 Commit Frequency

1. Commit every completed vertical slice (target every 30-90 minutes while actively coding).
2. Keep commits small and reviewable:
   1. Prefer one concern per commit.
   2. Avoid mixing refactor + behavior change in the same commit when possible.
3. Commit message format:
   1. `<type>: <concise change>`
   2. Body must include test evidence (commands run and result).

### 8.2 Push Frequency

1. Push after each stable checkpoint (minimum 3 pushes/day during active development).
2. Push immediately after any risky refactor so work is recoverable.
3. End every day with:
   1. Cleanly pushed branch.
   2. Short status note with what is done and what is next.

### 8.3 Local Test Frequency (macOS safety net)

Because Windows cannot be fully validated in this environment, we enforce frequent local checks to prevent collateral regressions.

Required checks:
1. Before first commit of the day:
   1. `PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile voice_to_claude.py`
   2. `bash -n install.sh autostart.sh voice`
2. Before every push:
   1. Re-run syntax checks above.
   2. Run targeted tests for touched modules.
   3. Run a lightweight runtime smoke test where possible:
      1. `./voice --debug` launch sanity (start path and log creation).
3. After any adapter/interface refactor:
   1. Validate the macOS path still boots and handles one PTT cycle.

### 8.4 Pre-Push Checklist (Mandatory)

1. `git status` reviewed and expected.
2. Local checks green.
   1. `./scripts/pre-push-check.sh`
   2. Use `./scripts/pre-push-check.sh --smoke` before risky merges.
   3. Includes `tests/unit` execution on every run.
3. No unresolved TODOs introduced without linked follow-up task.
4. README/plan/docs updated if behavior changed.
5. Commit history remains readable (no giant mixed commits).

Hook enforcement:
1. Configure hooks path once per clone:
   1. `./scripts/install-git-hooks.sh`
2. This runs checks automatically on every `git push`.

### 8.5 Failure Handling Rule

1. If pre-push checks fail, do not push.
2. Fix or revert immediately, then re-run checks.
3. If blocked, push to a clearly labeled WIP branch and note blockers in writing.

## 9. Acceptance Criteria by Layer

## 9.1 Functional

1. Press-and-hold PTT captures speech and transcribes on release.
2. Output reaches active app correctly for supported modes.
3. Config persists and survives restarts.
4. Startup toggle works.

## 9.2 Reliability

1. No crash after 100 consecutive PTT cycles in test loop.
2. No unbounded temp-file growth.
3. Transcription failure does not terminate app.

## 9.3 Performance

1. First transcription after model load within acceptable window on baseline hardware.
2. Regular short utterances processed with low latency target:
   1. P50 < 1.2s.
   2. P95 < 2.5s.

## 9.4 UX

1. Clear tray state changes for loading/ready/recording/processing/sending/error/paused.
2. Helpful error messaging for missing permissions/dependencies.

## 10. Test Plan

## 10.1 Unit Tests

Priority modules:
1. Dictation replacements and control commands.
2. Config normalization/migration.
3. State machine transitions.
4. Output mode mapping and send-key mapping.

## 10.2 Integration Tests

1. End-to-end mock pipeline:
   1. Synthetic WAV -> STT mock -> dictation -> output adapter mock.
2. Backend swap tests:
   1. MLX backend and Faster-Whisper backend share the same interface behavior.

## 10.3 Manual Regression Checklist (Windows)

Hardware/OS matrix:
1. Windows 11 (latest), Intel CPU.
2. Windows 11, AMD CPU.
3. Windows 10, Intel CPU.

Manual cases:
1. Launch app and verify tray icon appears.
2. Change PTT key and verify new key behavior.
3. Record short, medium, and long phrases.
4. Validate output in Notepad, VS Code, browser.
5. Toggle pause/resume repeatedly.
6. Toggle startup and reboot validation.
7. Turn notifications on/off and verify behavior.
8. Unplug/replug microphone during runtime.
9. Force network loss during model download and verify graceful errors.

## 10.4 Release Gate

Mandatory before beta:
1. All P0 tests pass.
2. No known crash-on-start bugs.
3. Installer works on clean VM.
4. Core text processing parity validated against macOS output samples.

## 11. Risk Register

## R1: Global hotkey instability in some environments
Impact: High  
Mitigation:
1. Hotkey adapter fallback.
2. Offer multiple key defaults.
3. Add diagnostic mode for key event logs.

## R2: Output automation blocked by app-specific security/policies
Impact: Medium-High  
Mitigation:
1. Document known unsupported apps.
2. Provide Copy Only fallback.
3. Add "Type mode" in parity phase.

## R3: Large binary size and dependency complexity
Impact: Medium  
Mitigation:
1. One-folder distribution for reliability.
2. Optional model presets to control footprint.

## R4: Defender/SmartScreen trust warnings
Impact: Medium  
Mitigation:
1. Code-signing roadmap.
2. Clear install docs and checksum publication.

## R5: STT quality/performance variance on low-end hardware
Impact: Medium  
Mitigation:
1. Default to smaller model on weak CPUs.
2. Expose model selector and performance guidance.

## 12. Observability and Support

Logging requirements:
1. Structured timestamped logs in platform-appropriate user config path.
2. Include:
   1. Startup diagnostics.
   2. Backend selected.
   3. Hotkey events (debug mode only).
   4. Transcription timing and failure reasons.

Support bundle command (planned):
1. `voice --diagnostics` creates a zip with:
   1. Recent logs.
   2. App version.
   3. Config (redacted sensitive fields).
   4. OS and Python/runtime metadata.

## 13. Security and Privacy

Principles to preserve:
1. Audio never leaves local machine by default.
2. No mandatory cloud account.
3. Least-privilege behavior for startup and automation.

Windows-specific controls:
1. Avoid admin requirement for normal operation.
2. Validate all subprocess calls and avoid shell injection paths.
3. Keep telemetry opt-in only (if ever added).

## 14. Release and Rollout Strategy

## Phase A: Internal alpha
1. Developer-only builds.
2. Rapid bug fixes on branch.

## Phase B: Closed beta
1. Small user cohort.
2. Collect:
   1. Crash logs.
   2. Hotkey conflicts.
   3. Output compatibility issues.

## Phase C: Public beta
1. GitHub release artifacts with clear "beta" tag.
2. Publish known issues list.

## Phase D: Stable
1. Remove beta label after stability threshold:
   1. No P0 bugs for 14 days.
   2. P1 volume below agreed threshold.

## 15. Documentation Deliverables

Must ship with Windows beta:
1. README sections:
   1. Windows install.
   2. Windows permissions and security prompts.
   3. Troubleshooting hotkeys/output/microphone.
2. CONTRIBUTING:
   1. Windows setup and test workflow.
3. Release notes template:
   1. New features.
   2. Known issues.
   3. Upgrade path.

## 16. CI/CD Plan

Build matrix:
1. macOS (existing).
2. Windows build job (new).

Enforcement additions:
1. Protect main branch with required status checks.
2. Reject merge if required tests are missing or failing.
3. Require PR description to include local test evidence.

Windows CI jobs:
1. Lint + unit tests.
2. Smoke tests on mocked adapters.
3. Packaging job:
   1. Build PyInstaller artifact.
   2. Upload artifact.
4. Optional signing job (if secrets present).

Promotion rules:
1. Tag `vX.Y.Z-beta.N` => beta artifacts.
2. Tag `vX.Y.Z` => stable artifacts.

## 17. Definition of Done (Windows MVP)

MVP is done only when all are true:
1. Installable Windows build exists and launches from tray.
2. Push-to-talk recording works with configurable key.
3. Transcription works offline after model is downloaded.
4. Output modes `paste_send`, `paste_only`, `copy_only` pass manual matrix.
5. Startup toggle works.
6. Logging and troubleshooting docs are published.
7. No open P0 defects.
8. Commit/push/test discipline was followed with traceable evidence in PR history.

## 18. Immediate Execution Plan (First 10 Working Days)

Daily baseline rule (every day before finishing):
1. Run required local checks.
2. Commit final changes of the day.
3. Push branch.
4. Log current status and next-step plan.

Day 1:
1. Create branch `feature/windows-foundation`.
2. Add core interfaces and adapter stubs.
3. Freeze current macOS behavior with baseline tests.
4. Make at least 2 small commits and push by end of day.

Day 2:
1. Move dictation/config/history into `core`.
2. Add config normalization unit tests.
3. Commit after each extraction milestone and push once tests pass.

Day 3:
1. Introduce STT backend interface.
2. Wrap existing MLX backend.
3. Run macOS smoke check before push.

Day 4:
1. Implement faster-whisper backend.
2. Add backend selection by OS/config.
3. Commit backend and selection wiring separately.

Day 5:
1. Wire macOS app through controller and adapters.
2. Regression pass on macOS.
3. Push only after full local checks pass.

Day 6:
1. Build Windows tray shell skeleton.
2. Add hotkey adapter and state transitions.
3. Keep commits small to isolate hotkey regressions.

Day 7:
1. Add output adapter (copy + paste path).
2. Validate Notepad and VS Code.
3. Push after each successful output-mode checkpoint.

Day 8:
1. Add startup manager and settings menu items.
2. Add notifications.
3. Run required local checks before every push.

Day 9:
1. Create `install_windows.ps1` and PyInstaller spec.
2. Produce first local Windows artifact.
3. Commit packaging scripts separately from runtime logic.

Day 10:
1. Run Windows manual checklist.
2. Triage defects and lock beta scope.
3. Publish summary with tested scenarios and unresolved gaps.

## 19. Open Decisions (Need Owner + Date)

1. Tray framework final choice:
   1. `pystray` (lighter) vs Qt-based tray (richer UI).
2. Output automation implementation:
   1. Native Win32 only vs optional pyautogui fallback.
3. Packaging format:
   1. PyInstaller one-folder only vs installer wrapper from day one.
4. Signing timeline:
   1. Beta unsigned vs sign before first public beta.
5. Model defaults:
   1. `tiny` for speed vs `base` for accuracy on Windows baseline.

## 20. Resourcing

Minimum:
1. 1 engineer full-time for 4 weeks.
2. 1 reviewer/tester part-time.

Recommended:
1. 2 engineers for first 3 weeks to reduce refactor risk and parallelize adapter work.

## 21. Final Notes

This plan intentionally prioritizes:
1. Architectural separation first (so Windows support is maintainable).
2. Shipping a narrow but stable MVP.
3. Protecting macOS stability while expanding platform coverage.
4. High-frequency commit/push/test loops to minimize hidden breakage.

Execution rule:
1. No Windows-specific shortcuts that bypass the new interfaces.
2. Every platform-specific behavior must live in an adapter.

Progress marker:
1. Initial package/interface scaffolding now exists under `app/` to support
   incremental extraction from `voice_to_claude.py`.
2. Configuration and dictation processing have been extracted into `app/core`
   and wired from `voice_to_claude.py` without behavior changes.
3. State metadata moved to `app/core/state.py` and macOS output automation moved
   to `app/platform/macos/output.py`.
4. MLX transcription backend wrapper moved to `app/stt/mlx_backend.py` and wired
   through `TranscriptionEngine`.
5. `TranscriptionEngine` orchestration and filtering moved to
   `app/core/transcription.py`.
6. `AudioEngine` moved to `app/core/audio.py` and wired from
   `voice_to_claude.py`.
7. macOS PTT hotkey handling moved to `app/platform/macos/hotkey.py` and wired
   from `voice_to_claude.py` (Quartz + pynput path preserved).
8. `TranscriptionEngine` now depends on the `TranscriptionBackend` protocol
   instead of MLX internals, with backend-injection unit tests added.
9. macOS protocol-friendly adapters added for hotkeys/output in
   `app/platform/macos`, and `voice_to_claude.py` now uses those adapters.
10. macOS autostart manager adapter added at
    `app/platform/macos/autostart.py` with unit tests.

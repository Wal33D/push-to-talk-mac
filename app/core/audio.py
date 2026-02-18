"""Audio capture engine for push-to-talk recording."""

from __future__ import annotations

import array
import tempfile
import wave

import pyaudio

from app.core.state import AppState


class AudioEngine:
    """Handles microphone input for push-to-talk recording."""

    def __init__(self, config, state_callback):
        self.config = config
        self.state_callback = state_callback
        self.running = False
        self.device_index = config.get("input_device", None)

    @staticmethod
    def list_input_devices():
        """List available audio input devices."""
        p = pyaudio.PyAudio()
        devices = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices.append(
                    {
                        "index": i,
                        "name": info["name"],
                        "channels": info["maxInputChannels"],
                    }
                )
        p.terminate()
        return devices

    def set_device(self, device_index):
        """Set the input device to use."""
        self.device_index = device_index
        self.config["input_device"] = device_index

    def get_audio_level(self, data):
        """Calculate the peak audio level from raw bytes."""
        audio_data = array.array("h", data)
        return max(abs(sample) for sample in audio_data) if audio_data else 0

    def record_until_released(self, stop_event, level_callback=None):
        """Record audio until stop_event is set (key released). For PTT mode."""
        p = pyaudio.PyAudio()

        try:
            stream_kwargs = {
                "format": pyaudio.paInt16,
                "channels": self.config["channels"],
                "rate": self.config["rate"],
                "input": True,
                "frames_per_buffer": self.config["chunk"],
            }
            if self.device_index is not None:
                stream_kwargs["input_device_index"] = self.device_index

            stream = p.open(**stream_kwargs)
        except Exception as exc:
            print(f"PTT: Failed to open audio stream: {exc}")
            self.state_callback(AppState.ERROR)
            p.terminate()
            return None

        frames = []
        rate = self.config["rate"]
        chunk = self.config["chunk"]
        max_chunks = int(120 * rate / chunk)  # 2 minute cap
        min_record_chunks = int(0.5 * rate / chunk)  # Record at least 0.5s no matter what
        tail_chunks = int(0.3 * rate / chunk)  # 0.3s extra after key release
        total_chunks = 0
        released = False

        self.state_callback(AppState.SPEAKING)

        try:
            while total_chunks < max_chunks:
                try:
                    data = stream.read(chunk, exception_on_overflow=False)
                except Exception:
                    continue
                frames.append(data)
                total_chunks += 1

                if level_callback is not None:
                    level_callback(self.get_audio_level(data))

                # Don't check stop_event until we've recorded the minimum
                if total_chunks < min_record_chunks:
                    continue

                # After minimum, check if key was released
                if not released and stop_event.is_set():
                    released = True
                    tail_remaining = tail_chunks

                # Record tail buffer after release for trailing audio
                if released:
                    tail_remaining -= 1
                    if tail_remaining <= 0:
                        break
        except Exception as exc:
            print(f"PTT recording error: {exc}")
            self.state_callback(AppState.ERROR)
            return None
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

        # Skip only if extremely short (< 0.3s of actual audio)
        min_useful_chunks = int(0.3 * rate / chunk)
        if total_chunks < min_useful_chunks:
            return None

        # Save to temp file
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wf = wave.open(f.name, "wb")
                wf.setnchannels(self.config["channels"])
                wf.setsampwidth(2)
                wf.setframerate(self.config["rate"])
                wf.writeframes(b"".join(frames))
                wf.close()
                return f.name
        except Exception as exc:
            print(f"PTT: Failed to save audio: {exc}")
            return None


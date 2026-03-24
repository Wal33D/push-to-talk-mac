"""Audio capture engine for push-to-talk recording."""

from __future__ import annotations

import array
import struct
import tempfile
import wave

import pyaudio

from app.core.state import AppState

import logging
LOG = logging.getLogger("pusha")


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

    @staticmethod
    def get_rms_level(frames):
        """Calculate RMS energy across all frames."""
        all_data = b"".join(frames)
        if len(all_data) < 2:
            return 0
        samples = array.array("h", all_data)
        if not samples:
            return 0
        sum_sq = sum(s * s for s in samples)
        return int((sum_sq / len(samples)) ** 0.5)

    @staticmethod
    def normalize_audio(frames, target_peak=24000):
        """Normalize audio to a target peak level for consistent Whisper input."""
        all_data = b"".join(frames)
        if len(all_data) < 2:
            return frames
        samples = array.array("h", all_data)
        peak = max(abs(s) for s in samples) if samples else 0
        if peak < 100 or peak >= target_peak:
            return frames  # Too quiet (noise) or already loud enough
        scale = target_peak / peak
        normalized = array.array("h", [max(-32768, min(32767, int(s * scale))) for s in samples])
        norm_bytes = normalized.tobytes()
        # Re-chunk to original frame sizes
        chunk_size = len(frames[0]) if frames else len(norm_bytes)
        return [norm_bytes[i:i + chunk_size] for i in range(0, len(norm_bytes), chunk_size)]

    def record_until_released(self, stop_event, level_callback=None, time_callback=None, tail_callback=None):
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
        silence_threshold = self.config.get("vad_silence_threshold", 500)
        vad_tail_max = self.config.get("vad_tail_max", 1.5)
        silence_countdown_chunks = int(0.3 * rate / chunk)  # 0.3s silence countdown
        max_tail_chunks = int(vad_tail_max * rate / chunk)  # Hard cap on tail
        total_chunks = 0
        released = False
        tail_chunks_elapsed = 0
        silence_remaining = silence_countdown_chunks

        self.state_callback(AppState.SPEAKING)

        try:
            while total_chunks < max_chunks:
                try:
                    data = stream.read(chunk, exception_on_overflow=False)
                except (IOError, OSError) as exc:
                    # Audio device disconnected or changed — try to reinitialize
                    print(f"PTT: Audio device error, attempting recovery: {exc}")
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                    try:
                        stream = p.open(
                            format=pyaudio.paInt16,
                            channels=self.config["channels"],
                            rate=rate,
                            input=True,
                            frames_per_buffer=chunk,
                        )
                        continue  # Retry with new default device
                    except Exception:
                        break  # Give up, return what we have
                except Exception:
                    continue
                frames.append(data)
                total_chunks += 1

                level = self.get_audio_level(data)
                if level_callback is not None:
                    level_callback(level)
                if time_callback is not None and total_chunks % 5 == 0:
                    elapsed = total_chunks * chunk / rate
                    time_callback(elapsed)

                # Don't check stop_event until we've recorded the minimum
                if total_chunks < min_record_chunks:
                    continue

                # After minimum, check if key was released
                if not released and stop_event.is_set():
                    released = True
                    tail_chunks_elapsed = 0
                    silence_remaining = silence_countdown_chunks
                    if tail_callback is not None:
                        tail_callback(True)

                # Energy-based VAD tail after key release
                if released:
                    tail_chunks_elapsed += 1
                    if level > silence_threshold:
                        # Speech still happening — reset silence countdown
                        silence_remaining = silence_countdown_chunks
                    else:
                        silence_remaining -= 1

                    # Stop if silence countdown expired OR hard tail cap hit
                    if silence_remaining <= 0 or tail_chunks_elapsed >= max_tail_chunks:
                        break
        except Exception as exc:
            print(f"PTT recording error: {exc}")
            self.state_callback(AppState.ERROR)
            return None
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

        # Skip only if extremely short (< 0.2s of actual audio)
        min_useful_chunks = int(0.2 * rate / chunk)
        if total_chunks < min_useful_chunks:
            LOG.info(f"PTT: Recording too short ({total_chunks} chunks < {min_useful_chunks} min), skipping")
            return None

        # Noise gate — skip if audio was just ambient noise
        rms = self.get_rms_level(frames)
        noise_gate = self.config.get("noise_gate", 50)
        LOG.info(f"PTT: Audio RMS={rms}, noise_gate={noise_gate}, chunks={total_chunks}")
        if rms < noise_gate:
            LOG.info(f"PTT: Audio below noise gate (RMS {rms} < {noise_gate}), skipping")
            return None

        # Normalize audio levels for consistent Whisper input
        frames = self.normalize_audio(frames)

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


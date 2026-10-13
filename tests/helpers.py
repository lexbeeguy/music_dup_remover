"""Synthetic audio generators shared by the tests."""
import array
import math
import os
import wave


def create_sine_wave_wav(filepath: str, duration: float = 3.0, sample_rate: int = 44100,
                         freq: float = 440.0, num_channels: int = 2) -> str:
    """Write a clean 16-bit sine-wave WAV file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    n = int(duration * sample_rate)
    samples = array.array("h")
    for i in range(n):
        v = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.extend([v] * num_channels)
    with wave.open(filepath, "w") as w:
        w.setnchannels(num_channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())
    return filepath


def create_melody_wav(filepath: str, seed: int, duration: float = 20.0, sample_rate: int = 22050) -> str:
    """
    Write a mono WAV with a stepped two-voice melody. Different seeds give
    acoustically different "songs"; the same seed at different sample rates
    gives the same song (useful for real Chromaprint matching tests).
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    steps_a = [0, 3, 5, 7, 10, 12, 7][seed % 3:] + [0, 3, 5, 7, 10, 12, 7][:seed % 3]
    base_a = 196.0 + 37.0 * seed
    base_b = 293.0 + 23.0 * seed
    rate_a, rate_b = 3 + seed, 2 + (seed % 2)
    samples = array.array("h")
    phase_a = phase_b = 0.0
    for i in range(int(duration * sample_rate)):
        t = i / sample_rate
        fa = base_a * 2 ** (steps_a[int(t * rate_a) % len(steps_a)] / 12)
        fb = base_b * 2 ** (steps_a[int(t * rate_b + 2) % len(steps_a)] / 12)
        phase_a += 2 * math.pi * fa / sample_rate
        phase_b += 2 * math.pi * fb / sample_rate
        samples.append(int(12000 * math.sin(phase_a) + 8000 * math.sin(phase_b)))
    with wave.open(filepath, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())
    return filepath

"""Original local test cues and lossless WAV preparation."""

from array import array
import math
from pathlib import Path
import random
import struct
import wave
from ..common import StudioError


def measure(path):
    try:
        with wave.open(str(path), "rb") as w:
            if w.getsampwidth() != 2 or w.getcomptype() != "NONE":
                raise StudioError(
                    "Local preparation supports uncompressed 16-bit PCM WAV; transcode an original copy with FFmpeg first"
                )
            raw = w.readframes(w.getnframes())
            samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
            peak = max((abs(x) for x in samples), default=0) / 32768
            rms = math.sqrt(
                sum((x / 32768) ** 2 for x in samples) / max(len(samples), 1)
            )
            return {
                "duration_seconds": w.getnframes() / w.getframerate(),
                "sample_rate": w.getframerate(),
                "channels": w.getnchannels(),
                "frames": w.getnframes(),
                "sample_width": 2,
                "peak_dbfs": 20 * math.log10(max(peak, 1e-12)),
                "rms_dbfs": 20 * math.log10(max(rms, 1e-12)),
            }
    except (OSError, wave.Error) as exc:
        raise StudioError("Audio input is missing or not a readable PCM WAV") from exc


def write_wav(path, samples, rate=48000, channels=1):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        data = array("h", (max(-32768, min(32767, round(s * 32767))) for s in samples))
        import sys

        if sys.byteorder != "little":
            data.byteswap()
        w.writeframes(data.tobytes())
    return measure(p)


def synthesize(path, duration=0.8, rate=48000, kind="response"):
    if not 0.05 <= duration <= 60 or rate not in {22050, 44100, 48000}:
        raise StudioError(
            "Cue duration must be 0.05–60 seconds and rate 22050, 44100 or 48000"
        )
    if kind not in {"response", "ambience", "footstep"}:
        raise StudioError("Unknown local cue kind")
    rng = random.Random(734)
    n = round(duration * rate)
    samples = []
    for i in range(n):
        t = i / rate
        envelope = math.sin(math.pi * i / max(n - 1, 1)) ** 2
        if kind == "response":
            value = (
                (
                    math.sin(2 * math.pi * (440 * t + 90 * t * t))
                    + 0.3 * math.sin(2 * math.pi * 660 * t)
                )
                * 0.18
                * envelope
            )
        elif kind == "ambience":
            # Integer cycles over the duration and zero endpoints support a benign loop.
            value = (
                (
                    math.sin(2 * math.pi * round(80 * duration) * t / duration)
                    + 0.2 * math.sin(2 * math.pi * round(121 * duration) * t / duration)
                )
                * 0.035
                * envelope
            )
        else:
            value = rng.uniform(-1, 1) * 0.15 * math.exp(-12 * t) * envelope
        samples.append(value)
    return write_wav(path, samples, rate)


def prepare(
    source, destination, start=0.0, end=None, gain_db=0.0, fade_seconds=0.01, loop=False
):
    info = measure(source)
    end = info["duration_seconds"] if end is None else end
    if (
        not 0 <= start < end <= info["duration_seconds"]
        or not 0 <= fade_seconds <= (end - start) / 2
        or not -60 <= gain_db <= 24
    ):
        raise StudioError("Invalid trim, fade or gain range")
    if Path(source).resolve() == Path(destination).resolve():
        raise StudioError("Keep the source; prepare into a different runtime file")
    with wave.open(str(source), "rb") as w:
        w.setpos(round(start * w.getframerate()))
        raw = w.readframes(round((end - start) * w.getframerate()))
    values = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    channels = info["channels"]
    frames = len(values) // channels
    fade = round(fade_seconds * info["sample_rate"])
    scale = 10 ** (gain_db / 20)
    samples = []
    for i, value in enumerate(values):
        frame = i // channels
        envelope = (
            min(1, frame / max(fade, 1), (frames - 1 - frame) / max(fade, 1))
            if fade
            else 1
        )
        samples.append(value / 32768 * scale * envelope)
    result = write_wav(destination, samples, info["sample_rate"], channels)
    result.update(
        loop=loop, loop_start_seconds=0, loop_end_seconds=result["duration_seconds"]
    )
    return result

"""Explicit single-request effects, speech and instrumental music profiles."""

from pathlib import Path
import re
import math
from ..common import StudioError, digest
from ..config import credential
from .requests import budget_check, archive_audio


def profile(operation, body):
    if not isinstance(body, dict):
        raise StudioError("Audio request must be an object")
    result = dict(body)
    for key in ("text", "prompt", "voice_id", "model_id"):
        if key in result and (not isinstance(result[key], str) or not result[key]):
            raise StudioError(key + " must be a nonempty string")
    for key in ("duration_seconds", "prompt_influence", "music_length_ms"):
        if key in result and (
            type(result[key]) not in (int, float) or not math.isfinite(result[key])
        ):
            raise StudioError(key + " must be a finite number")
    for key in ("loop", "force_instrumental"):
        if key in result and type(result[key]) is not bool:
            raise StudioError(key + " must be a boolean")
    if "voice_settings" in result:
        settings = result["voice_settings"]
        if not isinstance(settings, dict) or set(settings) - {
            "stability",
            "similarity_boost",
            "style",
            "use_speaker_boost",
            "speed",
        }:
            raise StudioError("Unsupported voice settings profile")
        for key, value in settings.items():
            if key == "use_speaker_boost":
                if type(value) is not bool:
                    raise StudioError("use_speaker_boost must be a boolean")
            elif (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not ((0.7 <= value <= 1.2) if key == "speed" else (0 <= value <= 1))
            ):
                raise StudioError("Voice settings are outside the supported range")
    if operation == "effects":
        allowed = {"text", "duration_seconds", "prompt_influence", "loop", "model_id"}
        if not isinstance(result.get("text"), str) or not result["text"]:
            raise StudioError("Effects need text")
        if not 0.5 <= result.get("duration_seconds", 0) <= 30:
            raise StudioError("Effects require explicit duration 0.5–30 seconds")
        if not 0 <= result.get("prompt_influence", 0.3) <= 1:
            raise StudioError("prompt_influence must be 0–1")
        result.setdefault("model_id", "eleven_text_to_sound_v2")
        if result["model_id"] != "eleven_text_to_sound_v2":
            raise StudioError("Effects profile supports eleven_text_to_sound_v2")
        endpoint = "/v1/sound-generation"
    elif operation == "speech":
        allowed = {"text", "voice_id", "model_id", "voice_settings"}
        if (
            not isinstance(result.get("text"), str)
            or not 1 <= len(result["text"]) <= 5000
        ):
            raise StudioError("Speech requires 1–5000 characters")
        voice = result.get("voice_id", "")
        if not re.fullmatch("[A-Za-z0-9_-]+", voice):
            raise StudioError("Speech requires an explicit licensed voice_id")
        if not result.get("model_id"):
            raise StudioError(
                "Speech requires an explicit model_id checked for the selected voice/language"
            )
        endpoint = "/v1/text-to-speech/" + voice
    elif operation == "music":
        allowed = {"prompt", "music_length_ms", "model_id", "force_instrumental"}
        if (
            not result.get("prompt")
            or not 3000 <= result.get("music_length_ms", 0) <= 600000
        ):
            raise StudioError(
                "Music requires prompt and explicit duration 3000–600000 ms"
            )
        result.setdefault("model_id", "music_v2")
        if result["model_id"] != "music_v2":
            raise StudioError("Music profile supports music_v2")
        result.setdefault("force_instrumental", True)
        endpoint = "/v1/music"
    else:
        raise StudioError("Unknown hosted audio operation")
    if set(result) - allowed:
        raise StudioError("Unsupported audio request fields")
    return endpoint, result


def generate(
    config, operation, body, record_path, output, budget, provenance, transport=None
):
    endpoint, request = profile(operation, body)
    budget_check(budget)
    if not isinstance(provenance, dict) or not provenance.get("rights"):
        raise StudioError("Record source/voice rights before hosted audio generation")
    key = credential(config, "elevenlabs")
    path = Path(output)
    if path.suffix != ".mp3" or path.exists():
        raise StudioError("Choose a new .mp3 output; preserve existing originals")
    record = {
        "schema_version": 1,
        "provider": "elevenlabs",
        "operation": operation,
        "endpoint": endpoint,
        "request": request,
        "request_digest": digest(request),
        "budget": budget,
        "provenance": provenance,
        "status": "SUBMITTING",
        "live_quality": "unverified",
    }
    wire = {k: v for k, v in request.items() if k != "voice_id"}
    fmt = "mp3_44100_128" if operation != "music" else "mp3_48000_192"
    return archive_audio(record_path, output, record,
                         "https://api.elevenlabs.io" + endpoint + "?output_format=" + fmt,
                         {"xi-api-key": key, "Content-Type": "application/json"},
                         wire, key, transport)

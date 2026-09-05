"""Narrow Fish REST file speech. No streaming lifecycle or implicit model fallback."""
from ..common import StudioError, digest
from ..config import credential
from .requests import budget_check, archive_audio

MODELS = {"s1", "s2-pro", "s2.1-pro", "s2.1-pro-free"}


def profile(operation, body):
    if operation != "speech" or not isinstance(body, dict):
        raise StudioError("Fish profile supports speech only")
    if set(body) - {"text", "model_id", "reference_id"}:
        raise StudioError("Unsupported Fish file speech fields")
    if not isinstance(body.get("model_id"), str) or body["model_id"] not in MODELS:
        raise StudioError("Fish requires an explicit supported model; never rely on fallback")
    if any(not isinstance(body.get(k), str) or not body[k].strip() for k in ("text", "reference_id")):
        raise StudioError("Fish requires text and an explicitly authorized reference_id")
    return {"text": body["text"], "reference_id": body["reference_id"],
            "format": "mp3", "sample_rate": 44100, "mp3_bitrate": 128}


def generate(config, operation, body, record_path, output, budget, provenance, transport=None):
    wire = profile(operation, body)
    budget_check(budget)
    if not isinstance(provenance, dict) or not provenance.get("rights"):
        raise StudioError("Record source/voice rights before hosted audio generation")
    key = credential(config, "fish")
    record = dict(schema_version=1, provider="fish", operation=operation,
                  endpoint="/v1/tts", transport="buffered_rest_file",
                  request={**wire, "model_id": body["model_id"]},
                  request_digest=digest({**wire, "model_id": body["model_id"]}),
                  budget=budget, provenance=provenance, live_quality="unverified")
    return archive_audio(record_path, output, record, "https://api.fish.audio/v1/tts",
                         {"Authorization": "Bearer " + key, "Content-Type": "application/json",
                          "model": body["model_id"]}, wire, key, transport)

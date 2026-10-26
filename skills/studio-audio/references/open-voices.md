# Open voices

Speech recipes for [character voices](character-voices.md), run by [studio-cloudrun](../../studio-cloudrun/SKILL.md). All are **experimental**: pinned and checked offline, not yet run by the kit. Each `recipe.json` has the exact commits, file hashes and `tested` status.

| Recipe | Model (licence) | Reference | Controls it reads | Notes |
|---|---|---|---|---|
| `casting-qwen3-voicedesign` | Qwen3-TTS 12Hz 1.7B VoiceDesign (Apache-2.0) | none: makes one | `instruct` (voice description), `temperature`, `top_p`, `top_k`, `repetition_penalty` | Casting only. Describe a voice, never a person. |
| `speech-chatterbox-en` | Chatterbox, original English model (MIT) | required (audio) | `exaggeration`, `cfg_weight`, `temperature` | Every take carries Resemble's Perth imperceptible watermark. Lower `cfg_weight` with high `exaggeration` for shouted lines. |
| `speech-qwen3-base` | Qwen3-TTS 12Hz 1.7B Base (Apache-2.0) | required (audio + exact transcript) | `temperature`, `top_p`, `top_k`, `repetition_penalty` | No instruction input: delivery stays intent. |
| `speech-cosyvoice3` | Fun-CosyVoice3 0.5B 2512 (Apache-2.0) | required (audio + exact transcript) | `speed`, `instruct` (spoken style, e.g. "Say it as a shouted rally.") | Uses `llm.pt`, not the RL variant. |

A control a recipe does not list is refused at validation, so nobody believes it was applied.

Excluded for commercial lines: OmniVoice (non-commercial weights), F5-TTS weights, Fish S2 Pro open weights, IndexTTS-2. Hosted ElevenLabs and Fish speech stay available through `studio audio` with their own rights and budget rules.

## Plans

```json
{
  "language": "en",
  "character": {"id": "striker", "profile_version": 1},
  "reference": {"input": "striker-reference.wav", "sha256": "<64 hex>", "transcript": "<exact words>"},
  "max_seconds": 4,
  "controls": {"exaggeration": 0.7},
  "cues": [{"id": "striker-ult-ally", "line_id": "striker.ult.ally", "text": "Overdrive! Keep up!",
            "delivery": "shouted rally", "seeds": [101, 102, 103]}],
  "repeats": [{"cue": "striker-ult-ally", "seed": 101, "after_reload": true}]
}
```

The job lists the reference under `inputs` with the same SHA-256 and `"private": true`; see [job format](../../studio-cloudrun/references/job-format.md). Casting plans have no `reference` and need `controls.instruct`.

## What a run gives back

Per take: `originals/<cue>-<seed>.wav` (float, untouched), `previews/<cue>-<seed>.wav` (PCM16 at RMS -20 dBFS, peak at most -1 dBFS, so takes compare at equal loudness), and an entry in `receipt.json` with text, line id, delivery, seed, controls, length, `overlength`, hashes, and the kit commit, engine commit, model revision, licence and reference hash. A repeat adds `same_bytes` and `same_frames`: whether the engine gave the same take back after a reload. Weights are downloaded file by file and checked against their pins, then the hub is switched offline, so nothing else is fetched mid-run.

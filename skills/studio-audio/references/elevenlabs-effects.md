# ElevenLabs effects

Adapted from ElevenLabs `sound-effects/SKILL.md` at `fd7b7f593b86861758bb1804234f758da3989f14`; MIT, Copyright (c) 2024 ElevenLabs. [License](../../../third_party/elevenlabs/LICENSE). Studio adaptation removes SDK/CLI installation dependencies and replaces the external installation link with [provider setup](../../../docs/provider-setup.md). No upstream code is vendored or downloaded during production.

The studio profile sends `POST /v1/sound-generation` with text, explicit duration (0.5–30 seconds), optional prompt influence (0–1), loop flag and `eleven_text_to_sound_v2`. It requests MP3 and preserves the original response before preparation. Check model availability, account rights and current rates before an authorized run. [Primary API reference](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert).

Describe a concrete source/action/material and acoustic perspective: a hollow ceramic tap beside a small pool, a soft rustling frond, or distant low wind. Separate layered roles when the game must mix them independently. For ambience request a loop, then listen across the seam in engine; the flag is not acceptance evidence.

Place request, budget and rights JSON in GAME, then use:

```text
python <KIT>/scripts/studio.py audio effects --project <GAME> --request requests/effect.json --budget requests/budget.json --provenance requests/rights.json --record artifacts/tasks/effect-001.json --output source/effect-001.mp3 --config <HOST>
```

A unique task record is claimed before one POST. Errors leave an ambiguous status and do not auto-regenerate. Provider error bodies and keys are not printed. Decode/measure a runtime copy, map its event/bus and record listening in the cue manifest.

# ElevenLabs music

Adapted from ElevenLabs `music/SKILL.md` and `music/references/api_reference.md` at `fd7b7f593b86861758bb1804234f758da3989f14`; MIT, Copyright (c) 2024 ElevenLabs. [License](../../../third_party/elevenlabs/LICENSE). Advanced finetuning, inpainting, video upload, SDK/CLI setup and their external reference dependencies were intentionally removed. The studio exposes a narrow prompt-based composition profile; [provider setup](../../../docs/provider-setup.md) replaces upstream installation instructions.

The profile sends `POST /v1/music` with `prompt`, explicit `music_length_ms` (3000–600000), `model_id: music_v2`, and optional `force_instrumental` (studio default true). It requests `mp3_48000_192`. Check current model access, duration/account limits, usage rights and estimated cost before a run. [Primary compose reference](https://elevenlabs.io/docs/api-reference/music/compose).

Describe mood, instrumentation, tempo/energy, texture and the encounter's pacing. Use original direction, not copied lyrics or a named artist imitation. For interactive music, plan intro/loop/outro or intensity stems as project requirements; a generated single track does not automatically provide seamless transitions or independently mixable stems.

Run `audio music` with the project/request/budget/provenance/record/output flags shown in [effects](elevenlabs-effects.md). Preserve the original and request metadata, prepare runtime edits separately, map to a music bus, and listen at the player's actual mix level. Do not claim composition-plan, streaming, finetuning or live entitlement support from these contract-tested prompt operations.

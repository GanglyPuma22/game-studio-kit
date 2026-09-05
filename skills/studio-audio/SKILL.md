---
name: studio-audio
description: Produce and prepare game effects, ambience, foley, dialogue and music, preserving originals and mapping cues to runtime events, buses and listening evidence.
---

# Studio audio

Inputs: encounter event map, location/distance, mix intent, voice identity/rights when applicable, duration/loop/variation needs and work-card budget. Output original files, prepared runtime audio and [cue manifest](../../templates/audio-cues.json).

For local functional audio use the deterministic PCM helper:

```text
python <KIT>/scripts/studio.py audio local --project <GAME> --kind response --duration 0.8 --output source/response.wav
python <KIT>/scripts/studio.py audio prepare --project <GAME> --source source/response.wav --output assets/response.wav --fade 0.01
python <KIT>/scripts/studio.py audio measure --project <GAME> --source assets/response.wav
```

Select effects for discrete feedback, foley for material/contact variations, ambience for place, voice for approved dialogue and music for pacing. Do not place all roles on an undifferentiated master bus. Define event ID, bus, priority, attenuation, concurrency and interruption behavior. Keep fictional companion identity separate from provider voice ID. A procedural tone validates timing/mix wiring; it does not certify the final character voice.

For hosted generation select `--provider elevenlabs` (the preserved default) or `--provider fish` explicitly. Fish supports only narrow REST file speech: read [Fish speech](references/fish-speech.md) for that route. For ElevenLabs read [ElevenLabs effects](references/elevenlabs-effects.md), [speech](references/elevenlabs-speech.md) or [music](references/elevenlabs-music.md) only for the selected route. The stdlib adapter performs one bounded, authorized request with a durable intent record and archives MP3. It never auto-retries an uncertain paid result. Preserve voice/provider/model IDs as actually used and the rights decision. No default model download or live provider call occurs during setup.

Prepare a runtime copy: trim intentionally and choose boundary treatment, normalize only to the project's mix intent and avoid clipping. The local helper supports 16-bit PCM WAV; keep encoded originals and use explicitly detected FFmpeg/FFprobe for other formats. Record measured channels, sample rate, duration, peaks and loop points; listen to seams and repeated variations rather than trusting a loop flag.

Wire cues in [Godot](../studio-godot/SKILL.md), listen to the captured runtime mix through an actual playback route, then record timing, distance, overlaps, clipping and voice suitability separately. Use [acceptance](../../references/acceptance.md). A screenshot and an audio player's active flag cannot pass listening review.

Treat speech, human vocal expression, SFX/foley, ambience, music, preparation and runtime review as separate capabilities. Human laughter/sighs may be speech-model expression; this is not general creature/SFX support. Fish is not a surf or music backend. A voice comparison uses the same text/language/intent, separate licensed provider voices, matched playback levels and one explicit total budget covering both calls. With zero generation budget, prepare the comparison and mark generation/listening not_run; even a free-named model must not submit. No provider error permits fallback or automatic resubmission.

The local fade helper applies endpoint fades only, **not an overlap crossfade**; `--loop` records intent, not seam quality. Follow [imported loop units](references/imported-loops.md) and record actual multi-cycle listening. File speech does not implement live companion transport; [companion delivery](../../references/companion-delivery.md) covers design boundaries only.

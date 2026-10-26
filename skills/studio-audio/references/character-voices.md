# Character voices

One voice per character, used for every line that character speaks. The voice is a private reference clip; open speech models read the game's exact lines in it. Engines and their terms are in [open voices](open-voices.md); the runs go through [studio-cloudrun](../../studio-cloudrun/SKILL.md).

## Rights first

- Commercial use needs both a model licence that allows it and a right to the voice. A model licence never grants the voice: use a voice designed from a written description (casting) or a recording of someone who agreed in writing.
- Never imitate a real person: no names, no "sounds like", no clips of actors, streamers or other games' characters as references.
- A reference made with a non-commercial model (for example OmniVoice) is not usable, even if the final engine is commercial.
- The reference is private. It goes to the runtime as a job input and nowhere else: never into results branches, receipts (they keep its SHA-256 and transcript only), public repos or chat.

## Steps

1. **Profile.** Fill [character-voice.json](../../../templates/character-voice.json): who they are in a line, age range, energy, pitch, accent, and what the voice must never be. Bump `profile_version` when the profile changes; plans name the version they were made for.
2. **Line sheet.** Fill [voice-lines.json](../../../templates/voice-lines.json): one entry per line with a stable `line_id` (`<character>.<event>.<variant>`), exact text, delivery intent and a `max_seconds` ceiling. Delivery is intent for the person listening; only controls the recipe lists change the engine.
3. **Casting.** A `casting-qwen3-voicedesign` job with the profile as `controls.instruct` and a casting read (a few lines in the character's range) on two or three seeds. Start free: `"where": "attended"` in a notebook the person watches. A person picks one take, or none and the description changes.
4. **Reference.** The picked take (or an authorized recording) becomes the private reference: 5-15 s, one speaker, no music, the exact transcript written down. Record its path, SHA-256, origin and consent in the profile.
5. **Audition.** The same lines, same seeds and same reference through each speech recipe ([open voices](open-voices.md)), with a repeat after reload to see whether the engine is stable. One `budget` group caps the whole audition when it runs on the service.
6. **Blind listening.** Previews are level matched. Play them without engine names; per take record fits / wrong delivery / artefact / unintelligible, and whether it still sounds like the same character. Pick the engine and controls for this character; write them into the profile.
7. **Lines.** Generate the line sheet with the picked engine. Listen to every take; never ship one that only passed the receipt checks. A take marked `overlength` was kept whole: shorten the text or raise the ceiling, never trim a word off.
8. **Import.** Prepare with `studio audio prepare`, then add each cue to the [cue manifest](../../../templates/audio-cues.json) with `character_id` and `line_id`, keeping the receipt beside the original.

## Do not

- Mix engines or references within one character's shipped lines without a new listening pass.
- Switch engine, rerun, or raise spend after a failed run without asking.
- Put "AI" in player-facing text about the voices.

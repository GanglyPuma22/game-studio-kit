# Direction sheet: <subject>

<!-- One sheet per move, effect or shot, kept with the subject's source. Fill it before the brief;
     the brief links it. See skills/studio-direction-sheet/SKILL.md. Write values, not adjectives.
     Every decision is "made" with values or "waived: <reason>". D4 and D6 may be waived; the others may not. -->

- **Subject:** <character / move / effect / shot id>
- **Lane:** in-engine | video
- **Status:** draft | confirmed (by <owner or lead thread>, <date>)
- **Source and tuning:** <clip, effect script, tuning keys, or shot spec this sheet directs>
- **Reference for timing:** <recorded move, reference video, or none>

## D1. Look and palette

- Style phrase: <one phrase>
- Palette (2 to 4, each with a job):
  - <name> <value>: core / hot
  - <name> <value>: body
  - <name> <value>: rim / accent

## D2. The one moment

- Moment: <what happens, in one line>
- Hits at: <seconds or frame at N fps, or fraction of duration>
- Fires together on that frame: <damage, burst, sound, hit-stop, camera cut>

## D3. Anticipation, release, settle

| Phase | Silhouette | Length | Tuning value? |
|---|---|---|---|
| Anticipation | <pose, readable from the receiving view> | <s> | <key name, or "look only"> |
| Release | <fastest change> | <frames> | |
| Settle | <overshoot, then rest> | <s> | |

## D4. Smears and cadence

- Smears: <where, which frames> | waived: <reason>
- Stepped poses: <which clip tracks, on twos> | waived: <reason>
- Never stepped here: locomotion, blends, camera, telegraphs

## D5. Eye and empty space

- Focal point at the moment: <element>
- Stays quiet: <elements, how much below the focal point>
- Must not be hidden: <silhouettes, telegraphs, landing zones>

## D6. Loop

- <loop point and seam treatment> | waived: one-shot / narrative shot

## D7. Avoid

- Ledger query: `avoid_ledger.py query <ledger> --tag <a> --tag <b>` (<N> matches, <M> used)
- <ledger id>: <noun>, applies because <one phrase>
- <noun> (seen in <take or date>; new, ledger entry <id or "subject only">)

## Limits (in-engine)

- Information carried by synced state: <telegraph, zone, path>; cosmetic only: <list>
- Camera: no impulse beyond the game's settings
- Budget per emitter: <amount, lifetime, draw passes, collision off>

## Review

| Round | Take | Failed rows (keep-kill #) | Avoid nouns added | One thing changed next |
|---|---|---|---|---|
| 1 | | | | |

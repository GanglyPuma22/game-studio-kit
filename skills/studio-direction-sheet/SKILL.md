---
name: studio-direction-sheet
description: Before any animation, visual effect or generated video shot is briefed, fill a one-page direction sheet of seven decisions (look and palette, the one moment and when it hits, anticipation-release-settle, smears and cadence, where the eye goes, loop, avoid-list), then judge the result against its keep-or-kill checklist.
---

# Studio direction sheet

A brief that says what a move or shot *does* gets the generator's or the agent's average look back. A brief that also says how it *lands* gets a directed result. This skill is the page that holds those decisions. It sits before the brief and after the result:

1. **Before:** query the game's [avoid ledger](references/avoid-ledger.md) for the subject's tags, then fill a [direction sheet](../../templates/direction-sheet.md) for the move, effect or shot. The brief to the builder (an agent, a generator, a person) links the sheet. Work does not start with an empty required decision.
2. **After:** review the result against the sheet with the [keep-or-kill checklist](references/keep-kill.md) for its lane. Each "no" names the decision that failed. A killed take adds its failure to the sheet's avoid-list, and to the ledger when it would bite another subject.

It holds no animation, effects, engine or generation craft. The building routes to the skill that owns it: [studio-animation](../studio-animation/SKILL.md) for clips and rigs, [studio-godot](../studio-godot/SKILL.md) for runtime effects and wiring, [studio-cinematic](../studio-cinematic/SKILL.md) for shots, [studio-video-gen](../studio-video-gen/SKILL.md) for paid runs, [studio-review](../studio-review/SKILL.md) for acceptance.

Inputs: the subject (one move, one effect, one shot), its lane (in-engine or video), the game's art contract and character palettes if they exist, the game's tuning values for anything timed, and the last killed takes. Output: a filled sheet stored with the subject's source (not in the kit), and after review a verdict per checklist row.

## The seven decisions

| # | Decision | What the sheet states | Required |
|---|---|---|---|
| D1 | The look and the palette | One style phrase; 2 to 4 named colours, each with a job (core, body, rim) | Yes |
| D2 | The one moment and when it hits | Exactly one hero moment and its time (seconds or frame, or a fraction of the duration) | Yes |
| D3 | Anticipation, release, settle | The three phases as visible silhouettes, with lengths; which length is a game value | Yes |
| D4 | Smears and cadence | Where smear shapes appear (fastest 1 or 2 frames only) and whether authored poses step on twos | Waive with a reason |
| D5 | Where the eye goes and the empty space | The focal point, what stays quiet, the contrast budget | Yes |
| D6 | The loop | Loop point and seam treatment, only for idles and ambient loops | Waive with a reason |
| D7 | What to avoid | 2 to 5 named failure shapes the reviewer can point at | Yes |

[Decisions](references/decisions.md) holds each one in full: parameters, why it reads, do and don't, and the failure it prevents. A decision is either **made** (concrete values) or **waived** with a one-line reason. "Default" is not a decision.

## Limits that outrank the seven

These are where the craft does not transfer to a real-time multiplayer game. They come from [decisions](references/decisions.md#limits-in-a-real-time-game) and hold on every sheet:

1. **No stepped cadence on locomotion, blend spaces, camera or camera-relative motion.** Step only authored action poses and smears. Stepped movement reads as stutter over a network, and a stepped telegraph can eat the opponent's reaction frames.
2. **Loops are for idles and ambient material only.** A one-shot ability or a narrative shot waives D6. A looping burst is a bug.
3. **Anticipation length is a balance value.** In a fight it is the opponent's reaction window. The sheet reads it from the game's tuning and never shortens it to make a move feel snappier. A different length is a balance change for the game's owner, made through its tuning, not a look pass.
4. **Information rides on synced state, not on cosmetic particles.** Telegraphs, impact zones, paths and anything a player reacts to come from replicated state with fixed parameters. Cosmetic particles may differ between clients because they carry no meaning.
5. **Effects never hide a telegraph, a silhouette or a landing zone,** and never add camera shake beyond the game's own camera limits. Sell impact with hit-stop, smears, a flash on the effect (not the screen) and the settle.
6. **Every new emitter states its budget** (count, lifetime, draw passes) in the sheet and in its scene.

## Rules

- **The sheet comes before the brief.** A builder handed a move or effect without a sheet fills one first, in minutes, from the subject's source and the game's tuning, and marks it `draft` until the owner or the lead thread confirms D1, D2 and D7.
- **One sheet per subject, kept with its source.** A character's moves share D1 and grow one avoid-list; each move has its own D2, D3 and D5.
- **Write values, not adjectives.** "Hits at 0.40 s, 12 frames at 30 fps", not "punchy". "No orb, no brown mush", not "high quality".
- **The reference wins for timing, the sheet wins for look.** When a reference video or recorded move exists, its timing stands; the sheet says what the moment is and how it looks.
- **Change one thing per round.** A retake changes the timing, the palette or the avoid-list, not all three, so the verdict teaches something.
- **Every killed take adds a noun to D7.** The avoid-list is the part of the sheet that pushes away from the average; it is built from failures actually seen.
- **The ledger remembers, it does not forbid.** D7 starts from the [avoid ledger](references/avoid-ledger.md) entries that match the subject's tags, cited by id, so nobody has to invent avoid-list entries on the spot. Retrying something the ledger records is allowed: say what is different this time, and mark the entry superseded if it works. Query by tag and paste only the matching lines; never the whole file.
- **Review in the decision's own view.** A game move is judged in the game's renderer at the player's distances, at full speed and frame-stepped, from the actor's camera and from the receiving player's camera. A shot is judged frame-stepped at 6 to 8 fps and at full speed.

## Lanes

| Lane | Sheet section | Review |
|---|---|---|
| In-engine: a move, an ability effect, an idle | [decisions](references/decisions.md) with the [in-engine mapping](references/decisions.md#in-engine-mapping) | [In-engine keep-or-kill](references/keep-kill.md#in-engine) |
| Generated video: one shot | [decisions](references/decisions.md) with the [video mapping](references/decisions.md#video-mapping) | [Video keep-or-kill](references/keep-kill.md#video) |

Return: the sheet's path and status (`draft`, `confirmed`), the review's row-by-row verdict with the frame or time where each "no" shows, the avoid-list nouns added, and one question for the owner if a required decision is still open.

# Character pipeline: owner gates, then end to end

Use this when the owner asks for a whole playable character (hero, enemy, companion) rather than one step of one. It is an order of work over the existing entrypoints, not a new craft: every stage below routes to the skill that already owns it. The owner approves the concept and the voice, plus the spend caps on the same page. A character whose look the owner will judge then passes three design gates from [studio-character-design](../../studio-character-design/SKILL.md): the target sheet, the grey body in a build and the look pick. Everything between gates runs without stopping until a playable build and one review page exist, unless a stop rule below fires.

Keep the run in one [character run record](../../../templates/character-run.json) (`kind: "character-run"`) beside the game's other records and check it with `validate-record` after every stage change. It is what a later session reads to resume the run without this conversation.

## Why gates

The concept and the voice are the two choices every later stage is judged against, and both are taste, not measurement. A builder that picks either one for itself measures later rounds against a target nobody agreed on ([concept and bases](../../studio-art-direction/references/concept-and-bases.md)). Most of what follows has a check a machine can run (model QA, motion checks, intelligibility, loudness, tests), so the owner's time goes to the gates and the final review page instead of each step.

The look is the exception. A concept fixes shape and mood; it does not say what "final" looks like in the engine, and no check measures that. The first version of this page had only the two gates, and the pilot that followed it found its final look by building one finished version after another (25 library versions; [audit](../../studio-character-design/references/pilot-audit.md)). The three design gates put those taste decisions where a round costs minutes: on a drawn target sheet, on a grey body, and on a bench of candidate looks, before the one production pass. A stand-in the owner will not judge for looks (a greybox body for a kit test) drops the three design gates and the `grey_build`, `look_bench` and `production` stages from its record.

## Before gate 1 (runs on its own)

1. **Brief.** Write the character brief in the run record's `brief`: role in play, abilities and how they read, scale and the closest player view, what it must not look like, three or four distinct look directions and a short voice profile (age, energy, accent range, what it must not sound like). Gameplay numbers come from the game; this run does not tune them.
2. **Free bases.** Bounded search with [studio-assets](../../studio-assets/SKILL.md) for a body base, parts and textures that fit the directions. Record every fetch in the asset ledger; note in the run record when nothing fits.
3. **Concept options.** About two images per direction through `art_pipeline.concept_route`. Archive prompt, tool and hashes as [concept and bases](../../studio-art-direction/references/concept-and-bases.md) step 2 asks.
4. **Voice casting.** A few takes per voice direction, each saying the same two or three real lines from the brief, through [studio-audio](../../studio-audio/SKILL.md) (a free or capped GPU run goes through [studio-cloudrun](../../studio-cloudrun/SKILL.md)). Check every take for intelligibility with a speech-to-text pass and drop the ones that blur a word. Rights and provider go in each take's receipt.
5. **Spend estimate.** For each paid route the later stages may use (mesh generation, hosted speech, rented GPU above the free allotment), write the estimated units and the cap you will ask for, after the read-only balance check of that provider.

Steps 3 and 4 run in parallel. Both feed one owner page.

## Gate 1 and gate 2: one owner page

Show the concept options, the voice takes and the spend caps together on one page (a decision card, a review page or a document the owner can answer from a phone). The owner picks a concept (or a stated mix with notes), picks a voice take and approves or edits each cap. If the voice is not ready yet, the concept gate can pass alone; the voice stages wait for gate 2 and the rest continues.

Record each answer in the run record's `gates`: who approved, when, the choice, the owner's notes and the hash of the chosen file. For the voice, the chosen file is the character's voice record when the audio skill keeps one (the experimental speech route in Kit PR #55 writes `character-voice.json` with the picked take, seed, prompt, model revision and reference hash); the voice lines stage reads the engine and reference from it, never from memory. The approver is `art_pipeline.concept_approver` for the concept and `character_pipeline.voice_approver` for the voice, never the builder. Approved caps become budget records ([production contracts](../../../references/production-contracts.md)); an unapproved paid route stays off for the whole run. A builder may mark a provisional pick only in an authorized unattended run, and nothing built on it can reach `review` until the owner confirms it.

## Design gates

After the concept gate, follow [studio-character-design](../../studio-character-design/SKILL.md). It owns what each gate shows, the round budgets and the rules; this page only places them in the run:

| Gate | The owner approves | Opens |
|---|---|---|
| `target` | The [target sheet](../../studio-character-design/references/target-sheet.md): "final" drawn on one page | `model` |
| `body` | The grey body playing its moves in a build | `look_bench` |
| `look` | One look picked from the [look bench](../../studio-character-design/references/look-bench.md) | `production` |

Each gate records its `rounds`. A gate past `gate_round_cap` without a yes is marked `stopped` and reported; the next step is a new target sheet version, not another round.

## Between the gates (runs on its own)

Run the stages in this order. Each one writes its outputs and its check result into the run record before the next starts. Stages without a dependency between them (animation and voice lines, for example) may run in parallel when the host allows it.

| Stage | Needs | Routes to | Done when |
|---|---|---|---|
| `model` | concept and target gates | [studio-blender](../../studio-blender/SKILL.md), [studio-meshy](../../studio-meshy/SKILL.md) or [studio-tripo](../../studio-tripo/SKILL.md) only within an approved cap | A scripted, rebuildable source composes the free base and separately built parts (garments, gear, weapons, hanging parts) into the runtime export. A paid generator takes the approved concept as reference and only fills a part no free base covered. The body passes its [report card](../../studio-character-design/references/body-report-card.md) on the reduced mesh; a failing body is regenerated or repaired here, not worked around later. |
| `model_qa` | `model` | [studio-model-qa](../../studio-model-qa/SKILL.md) | Every LOD of the model as the game assembles it has no FAIL, UNMEASURED or NOT SET row. Repair the model, never the check. |
| `library` | `model_qa` | the game's model viewer or asset library | The owner can open the exact runtime file in a viewer. The stills and QA report sit beside it. The library is the record of what was approved: update it at gates and after `production`, never per look idea, and never ask for a look approval on it. |
| `animation` | `model_qa` | [studio-animation](../../studio-animation/SKILL.md) (`character_pipeline.animation_route` names the method, for example boxes-first when the game opted in) | Every clip or pose the game's event table needs exists, with the game's motion checks passing on each. |
| `grey_build` | `animation` | [studio-godot](../../studio-godot/SKILL.md), [studio-playtest](../../studio-playtest/SKILL.md) | A build shows the skinned body in flat grey playing every move. The owner's yes is the `body` gate; the body is frozen after it. |
| `look_bench` | `grey_build`, body gate | [look bench](../../studio-character-design/references/look-bench.md) | A page of two or three candidate looks beside the target sheet, drawn by the game's renderer at the game's review distances, exists for each round. The owner's pick is the `look` gate. No shader variant, setting, library version, pull request or move recording is made here. |
| `production` | `look_bench`, look gate | [studio-godot](../../studio-godot/SKILL.md), [studio-blender](../../studio-blender/SKILL.md), [studio-animation](../../studio-animation/SKILL.md) | The picked look is built once as real assets and shader code, every move passes on the final body, the runtime file passes model QA again and the build matches its bench page at the same distances. |
| `voice_lines` | voice gate | [studio-audio](../../studio-audio/SKILL.md), [studio-cloudrun](../../studio-cloudrun/SKILL.md) | Every line in the line sheet exists in the approved voice (same engine, seed and reference as the approved take), passes intelligibility and is prepared to the mix intent. The cue manifest lists each line with provenance. |
| `effects` | `model` | [studio-godot](../../studio-godot/SKILL.md) and the game's effect rules | Each ability reads from its effect and sound, drawn at its real reach, on every target renderer. |
| `sounds` | `effects` | [studio-audio](../../studio-audio/SKILL.md) | Each ability and state has its sound with source, licence and loudness recorded. |
| `integration` | all of the above | [studio-godot](../../studio-godot/SKILL.md) | The character plays in the game behind a toggle that falls back to the old look, the game's tests pass and a build the owner can play exists. |
| `review` | `integration` | [studio-review](../../studio-review/SKILL.md) | One page shows the model, clips, effects and lines side by side with a verdict control per item. |

The line sheet comes from the brief and the game's event table (ability casts, ultimate, being hit, low health, death, round start and end, ally and enemy variants where the game has them). Keep lines short and in the character's profile; never put production notes or tool names in player-facing text.

## Stop rules

The run stops and reports to the owner only when:

- a paid route would pass its approved cap, a submission outcome is unknown, or a provider asks for a new account decision;
- the same check still fails after `character_pipeline.repair_round_cap` bounded repair rounds on one stage (report the failing rows and the last two attempts);
- a stage needs a choice that changes the approved concept, target sheet, voice or gameplay;
- a design gate reaches `gate_round_cap` rounds without the owner's yes (report the rounds side by side and the question they kept circling);
- the host loses a capability the remaining stages need.

A stop on one stage does not stop independent stages. A target miss or nonzero command result is triage, not a stop ([run policy](../../../references/run-policy.md)).

## After the review page

Each owner verdict maps to the stage that owns it: a colour, line or surface note reopens `production` when the bench page already shows what is asked, and `look_bench` when it does not; a shape or stance note reopens the `target` gate and `model` (and therefore everything built on the body), and says so before any work starts; a motion note reopens `animation`; a line note reopens `voice_lines` for that line only. Record the round in the run record and rebuild only the reopened stages and what depends on them. An approved item is kept as is in later rounds.

## Game settings

The project record's `character_pipeline` block holds the per-game values: the voice approver, the animation route, the repair round cap, the gate round cap, the review distances the look bench draws at (closest, usual and far, in metres), where the bench scene lives, where runtime files go and which model viewer is the library. A game's own skill adds its runtime rules (network cost, renderers, model API) on top; this page owns only the order and the gates.

---
name: studio-character-design
description: Take one character from an approved concept to final art in few owner rounds, with a drawn target sheet, a body that passes a report card, a grey body frozen in a build, a cheap look bench and one production pass.
---

# Studio character design

This is the order of work and the owner's checkpoints for making one character look right: what gets decided when, on what kind of picture, at what cost per round, and when to stop. It holds no modelling, generation, rigging or shader craft; every step routes to the skill that owns it (table at the end). Use it for any character whose look the owner will judge: a new one, or a remodel that changes how one looks. The [character pipeline](../studio-director/references/character-pipeline.md) runs voice, effects, sounds and integration around it and keeps both in one [character run record](../../templates/character-run.json).

Inputs: the approved concept ([concept and bases](../studio-art-direction/references/concept-and-bases.md)), the game's rig or rig plan, the closest and usual player views, and the game's art contract if it has one. Outputs: an approved target sheet, a frozen body, a picked look with its bench stills, and one production pass in a build.

## Why it exists

A look is cheap to change on paper and expensive to change in the engine. The pilot ([audit](references/pilot-audit.md)) had an approved concept that fixed the shape and nothing else. Colours, lines, eyes, glow and surface were found by building each idea as finished art and reacting to it: 20 library versions of one character in 16 days, 574 move takes, 58 settings, five shader variants and a 283-file pull request, against 2 to 6 versions for the three other characters built the same way. Each stage below moves one kind of decision to the cheapest place it can be made, and each rule names what went wrong before it existed.

## Stages

| # | Stage | The owner sees | Rounds | A round costs | Done when |
|---|---|---|---|---|---|
| 1 | Concept | Painted options on one page | 2 | minutes | Owner picks one or a stated mix ([concept and bases](../studio-art-direction/references/concept-and-bases.md)) |
| 2 | [Target sheet](references/target-sheet.md) | One page that draws "final": front, side, back and a close crop in the game's style, palette, where lines go, eyes, glow, what moves, effects, paint method | 3 | minutes | Owner approves it (`target` gate) |
| 3 | [Rig-fit picture](references/body-report-card.md#rig-fit-picture) | Nothing; builder's gate | - | minutes | The rig drawn over the generation picture fits: limbs apart, legs under the rig's hips, hanging parts left off |
| 4 | Body and [report card](references/body-report-card.md) | Nothing unless a row cannot pass | 3 generations | one generation or repair | Every row passes on the reduced mesh. A failing body is regenerated or repaired before any rig, paint or review |
| 5 | Grey body in a build | The body skinned to the rig in flat grey, playing every move, in a build | 2 | hours | Moves pass the [move check](../studio-animation/references/move-check.md) and the owner accepts shape and motion (`body` gate). The body is frozen |
| 6 | [Look bench](references/look-bench.md) | 2 or 3 looks beside the target sheet: stills at close, usual and far distance and one walk clip, from the game's renderer | 3 | under an hour | Owner picks one (`look` gate) |
| 7 | Production pass | The picked look, built once, in a build | 1, then small fixes | a day | Owner accepts it in play |

The target is 5 to 8 owner-visible looks per character and 11 at every cap.

## Rules

1. **Draw "final" before building it.** No body work starts on a concept alone. An owner who does not yet know what they want is the normal case, not a fault: the target sheet is where that exploring happens, with two or three contrasting answers to each open question on one page, because a round there costs minutes.
2. **One owner of stages 2 to 7.** One session or thread carries the character from target sheet to production pass and keeps the run record. The pilot's look passed through at least ten threads, each on its own branch, and each restarted from its own idea of the target.
3. **The owner judges in the game's renderer.** Approvals happen on a build or on bench stills drawn by the game's own renderer at the player's distances. A model viewer or asset library is the record of what was approved, updated at gates, never the place a look is first judged. The pilot's viewer disagreed with the game five times in two weeks, and each disagreement cost a round.
4. **No production cost on an unpicked look.** Until the `look` gate is approved there is no new shader variant, no new setting, no library version, no move re-recording, no code review and no full test run for a look idea. The run record refuses a `production` stage that starts before that gate. Three of the pilot's versions were code-review fixes on a look the owner had not accepted, and rejected at the next one.
5. **A new technique is named on the target sheet and built once.** The bench uses only what the game's shaders can already do. When a look needs something new (a second surface layer, lines from a new source), the sheet names it, the owner approves the sheet, and it is built in stage 7. The pilot reworked its line method four times and its hanging mane seven ways, each as finished art.
6. **Every send carries its comparison.** Before anything goes to the owner, the builder looks at a close crop beside the target sheet and beside the last accepted version, at the three distances. A send that is worse than the accepted version in any of them is not sent. The pilot's last rejected round (lines that read as scribble, eyes in the wrong place) was visible in that crop.
7. **Three rounds, then fix the target.** A stage that reaches its round budget without a yes stops. The next step is a new target sheet version that settles what the rounds disagreed on, not a fourth round. The run record counts rounds per gate and refuses a fourth without a `stopped` status.
8. **The body is frozen at stage 5.** After the `body` gate, shape, proportions, stance and mesh do not change for look reasons. A look note that needs a different body reopens stage 2, and says so.
9. **Hanging parts are their own parts.** Manes, chains, capes and tails are left off the generation picture and built separately with their own motion, attached at stage 5. Fused into the body they cannot move without tearing it.

## Paint method

The target sheet names one of three, because the choice sets what the body must pass at stage 4:

- **Flat paint**: one palette colour per part, stored in vertex colours, with the game's shader adding light and lines. Needs no texture layout. Shows nothing smaller than a triangle.
- **Flat paint plus shader detail**: grain, frost or wear projected by the shader. Needs no layout. Cannot place one particular mark in one particular spot.
- **Painted texture**: placed detail finer than the mesh. Needs a texture layout that can hold paint, which is a report card row; a generator's or remesher's automatic layout usually fails it and is redone once in Blender before stage 6.

A harder method is not a reason to refuse it; it is a reason to pay its fixed cost once at stage 4 instead of every look round.

## Record

The [character run record](../../templates/character-run.json) carries three design gates beside `concept` and `voice`: `target`, `body` and `look`, each with the chosen file's hash, the approver and a `rounds` count. `validate-record` refuses a stage that starts before its gate, a builder approving its own gate, a `production` stage before an approved or provisional `look`, and a gate past `gate_round_cap` (3 unless the record says otherwise) that is not `stopped`. It cannot check that a person approved anything.

## Routes

| Step | Skill |
|---|---|
| Concept options, the art contract, a free base | [studio-art-direction](../studio-art-direction/SKILL.md), [studio-assets](../studio-assets/SKILL.md) |
| Generation from the approved picture | [studio-tripo](../studio-tripo/SKILL.md) or [studio-meshy](../studio-meshy/SKILL.md), inside an approved cap |
| Inspect, reduce, repair, layout, bake, hand modelling | [studio-blender](../studio-blender/SKILL.md) |
| Skinning a generated body, block rigs, moves, the move check | [studio-animation](../studio-animation/SKILL.md): [generated mesh skin](../studio-animation/references/generated-mesh-skin.md), [move check](../studio-animation/references/move-check.md) |
| Attachment, clipping, see-through and LOD checks on the runtime file | [studio-model-qa](../studio-model-qa/SKILL.md) |
| Detail that reads at play distance in an outlined look | [outline readability](../studio-blender/references/outline-readability.md) |
| Bench scene, shader parameters, the build | [studio-godot](../studio-godot/SKILL.md), [studio-playtest](../studio-playtest/SKILL.md) |
| Stills and clips drawn with nobody at the machine | [studio-cloudrun](../studio-cloudrun/SKILL.md) |
| Final acceptance | [studio-review](../studio-review/SKILL.md) |

A game's own skill adds its values on top: distances, renderer, palette, the rig, where the bench scene lives and which viewer is the library.

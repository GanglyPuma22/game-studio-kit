# Look bench: pick the look before paying for it

A small scene in the game project that draws the frozen body in two or three candidate looks with the game's own renderer and writes the pictures an owner needs to choose. It answers "which look" for under an hour a round. Nothing on it is finished art, and nothing on it is merged.

It exists because the pilot tried each look idea as a finished version: a shader variant, a bake tool, settings, a library version, 22 to 30 re-recorded moves, a test run and two code reviews, before the owner had seen it. Twelve versions followed the one the owner still pointed to as the best, and by the audit's judgment eight of them were a look question asked at production cost.

## What the bench draws

For each candidate look, from the game's renderer with the game's light, field of view and resolution:

- a still at the closest player view, at the usual fighting distance and at the far distance the character is first seen from. The audit proposed close, 20 m and 60 m for the pilot's game; take the values from the game's own skill;
- one short clip of the walk or idle, because lines and layered surfaces that hold in a still can crawl in motion;
- the same crops of the target sheet and of the last accepted version, on the same page, at the same size.

One page per round. Far crops are enlarged by whole numbers with nearest-neighbour scaling so a screen pixel stays a square ([outline readability](../../studio-blender/references/outline-readability.md)).

Draw with the renderer players get. A cloud or headless host that falls back to a different renderer can draw the same shader visibly paler or darker; when the bench cannot use the players' renderer, say so on the page and do not take a colour decision from it ([cloud runtime notes](../../studio-cloudrun/references/runtime-notes.md) has the driver that draws the full renderer without a GPU).

## What a candidate may use

- Parameters the game's shaders already have.
- Vertex colours and texture files saved as bench files beside the scene.
- The body exactly as frozen at stage 5, in its rest pose and one move.

## What stays off the bench

- New shader variants or techniques. If a look needs one, it goes on the target sheet's list, the owner approves the sheet, and it is built once in stage 7. A throwaway mock-up of the technique in the bench scene is allowed when it is labelled as one and deleted after the pick.
- New player-facing settings or sliders.
- A model viewer or library version, a pull request, code review, a full test run, or re-recording moves.
- Changes to the body.

## A round

1. Two or three candidates, each differing from the others in one named thing (line source, core colour, snow coverage). A page of five looks that each differ in four ways cannot be answered.
2. The builder's own check first ([rule 6](../SKILL.md#rules)): close crop beside the target sheet and the last accepted version at all three distances. Drop a candidate that is worse than the accepted version anywhere.
3. One page to the owner. The owner picks one, or a stated mix that becomes a candidate in the next round.
4. Count the round in `gates.look.rounds`. Three rounds; then stop and take the open question back to the [target sheet](target-sheet.md).

## After the pick

Record the pick in `gates.look` with the hash of the bench page, the approver and the date. Then stage 7 builds it once:

- the look as real assets and shader code, with only the settings a player or tuner needs;
- every move checked on the final body ([move check](../../studio-animation/references/move-check.md));
- the runtime file through [model QA](../../studio-model-qa/SKILL.md);
- the library or viewer updated once, with the approved version;
- one build, compared against the bench page at the same three distances before the owner sees it. A production pass that does not match its own bench page is a defect in the pass, not a new look round.

Delete the bench's losing candidates' files, keep the page.

## Checklist

- [ ] Body frozen; bench draws it with the game's renderer
- [ ] Stills at the three distances and one clip per candidate
- [ ] Target sheet and last accepted version on the same page
- [ ] Each candidate differs in one named thing
- [ ] No new shader, setting, library version, pull request or move recording
- [ ] Builder's comparison done before sending
- [ ] Pick recorded with the page's hash and the round count

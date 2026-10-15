# Critic loop for visible assets

A game opts in to this loop for anything a player looks at: models, ground and scatter, materials, creatures. The kit does not run it by itself, and a project without `art_pipeline.critic` keeps its own review practice. Once opted in, a builder runs it before showing the owner, so the owner's time goes to work that already clears the game's declared checks. It feeds [`review revision`](../../../docs/review-revisions.md) records; it does not grant acceptance, which stays with [acceptance](../../../references/acceptance.md) and the owner.

Per-game values live in the project record's `art_pipeline.critic` block ([project template](../../../templates/project.json)): `round_cap`, `stall_rounds`, `closest_view` and `review_place`. An unset value is undecided, not zero.

## Criteria

The game owns one criteria file; the kit owns how it is shaped. Each row has an `id`, a short title, a `pass_rule` a critic can point at in an image, `reference_ids` naming the absolute references it is judged against, and these fields, which the critic reads before judging:

- `evidence`: the kinds that can judge it (`still`, `frame_strip`, `clip`, `orbit`, `mesh_test`, `metric`, `in_game`). A round is planned from this list, so a criterion that needs a clip is never left to stills and marked "cannot judge".
- `authoritative`: which renderer or environment closes it (`engine`, `lab`, `either`). Lab renders can open a defect or pre-check one; only authoritative evidence closes it. Anything that depends on a custom shader, transparency, depth or fog is `engine`.
- `views`: which views count (a flat, ground-hugging asset needs a three-quarter-above view; side views alone make it a bar).
- `metric` (optional): a measured value with its tool and threshold, kept separate from the visual rule. A number is evidence unless the owner calibrated it; uncalibrated numbers are reported and never fail a row on their own.
- `owner` (optional): who owns the check when it is not the asset builder, for example placement on slopes or grouping in the world. A model-only round records such rows as `not_applicable` with that owner instead of failing them.
- A difference threshold names its measure, for example a colour difference in Lab ΔE between two regions, so a "small colour difference" is repeatable.
- Budgets are maxima. State them per size class in the game's settings; a small asset far under budget passes.

A starter set of model rows most games can adopt and reword: triangle budget per size class; no interpenetrating parts (measured against a rest-pose baseline for embedded joins); readable silhouette at play distance; close-up detail at the closest view; no visible pop at LOD switches; gradual far fade; grounded contact with what it stands on; palette fit to the setting; animation reads at a normal distance; rigid units stay together in motion (eye stalks, head plates and shells do not tear apart across frames). Lighting states (day, dusk, night) need their own rows when the game has them. Materials need a standard preview: scale bar, low and high sun, dry and wet variants when relevant, and normal and roughness thumbnails.

When an asset has an [approved concept](../../studio-art-direction/references/concept-and-bases.md), fit to it (silhouette, proportions, palette) is the craft row. Without one, craft concerns are notes for the owner.

## Round folder

One folder per round, `<loop>/roundN/`, holding:

- `candidate/`: a copy, or hashed references at a commit, of exactly what is judged, snapshotted before the next fix starts. Never a live working tree; an overwritten round cannot be judged again.
- `sheets/` for composed comparison images, `raw/` for the per-view stills they were made from, `clips/` for motion, `metrics/` for tool output (mesh tests, pop and colour measures). Critics compare far better than they judge alone, so every sheet puts the candidate beside a reference: the approved concept, the current shipped build or the previous round.
- `manifest.json`: build or content identity, engine version, flags, camera settings and the exact capture and metric script versions. A critic checks it against `candidate/` before judging; a stale capture is the most expensive mistake a loop can make. When content streams in or builds after start, the manifest also records a readiness probe (the layer or tile reported built before the capture), so a capture that missed a feature is not read as a candidate that lacks it.
- `changes.json`: a factual diff against the previous round (files changed, per-mesh triangle counts, texture hashes, which mesh parts moved), so the critic does not have to tell "not built" from "not visible".
- `critic.json`: the critic's output, shaped like the [critic template](../../../templates/critic.json).

Capture from the exported runtime file re-imported, not from the editable source: shader-only detail that the export drops must not pass. Hide collision and helper meshes the game hides. Frame every LOD on the full model's bounds, not the level's own (a far card's bounds are its whole plane). Pin capture and metric scripts in the game's repository and name their commit, so numbers compare across rounds and lanes.

## Independent critic

The critic is never the builder. Give it a fresh context with: the criteria rows it judges, the image and clip paths, the approved concept, the previous round's open defects to recheck, these judging rules, and the output template. It judges only what the evidence shows, gives each row `pass`, `fail`, `not_judged` (the evidence could not show it) or `not_applicable` (the row's `owner` is someone else and this round cannot reach it; name that owner) with the image and location, measures where it can, names what it could not judge and why, and writes `critic.json`. A shared brief file plus one round path per critic works well when several assets are reviewed in parallel; group assets by family per critic.

## Judging rules

1. Judge against an absolute reference (the approved concept, an owner-approved still or a reference photo set), not only the previous round. A candidate can win every relative comparison and still miss the look the owner wants.
2. Only declared criterion ids can fail. A concern without an id is a note for the owner. A lane that needs a new check asks the criteria owner to add it.
3. Close-up checks are judged at 1:1 game pixels from the closest view the player camera can reach (`closest_view`: resolution, FOV, eye height, distance). Upscaled or magnified crops are not evidence for a fail.
4. Numbers are evidence, not pass rules, unless the owner calibrated them. A visual row fails only when the critic can point at the defect in a game-distance image or a clip. Budgets and owner-calibrated metrics fail on the measurement itself, with the tool and value cited.
5. Gloss, wet, glass and translucent materials are judged only in a sky-lit scene (a lit 3D viewer or the game), never on a flat backdrop.
6. Motion rows (LOD pop, far fade, animation, shimmer) are judged from clips or frame strips. Do not mark them not judged when a clip can be made.
7. "Better than last shown" is a verdict that can go to the owner, with the open rows named, so one open defect does not hold back an asset the owner would want to see.
8. In-game rounds record the build identity and flags, and the critic checks them before judging.
9. Context questions (placement, use, feeding and reacting, groups, anything judged against its neighbours) go to an in-game capture before another lab round.
10. The owner's verdict outranks the critic. An owner-approved asset stops looping; from then on the critic checks only budgets and regressions against the approved round. Where the owner passes what the critic failed, add a calibration row to the game's criteria log; the criteria owner then loosens that check or makes it advisory.

## When to stop

- Stop when the planned rows pass, or when the only remaining blockers belong to another owner: name that owner and tell the person.
- `round_cap` (kit default 10): after that many rounds without a pass, stop, put the best round in front of the owner with the failing rows and their measured gaps, and move on.
- `stall_rounds` (optional): once only one row is failing, it gets at most this many more rounds before the best round goes to the owner. Unset means no stall limit. Separately, as a diagnostic that stops nothing, a row that fails the same way across several rounds is worth checking for a criterion the critic cannot judge from the evidence it gets; log it in the friction log.
- Best rounds go to the game's one review place (`review_place`, for example a 3D model viewer the owner uses), not a new page per asset.

## Recording the loop

Map each round into a `review-revision` record: candidate manifests, one evidence row per criterion and subject, and defects linked to before and after evidence with the critic's and root's rechecks. `python <KIT>/scripts/studio.py review revision --project <loop> --evidence roundN/review.json --report roundN/review-report.json` checks the linkage and writes the report to a new file beside the record; `--report` never overwrites, so use a new path each run (the round folder works). A critic `partly` recheck stays `open` in the record. Keep the owner's verdict out of the record until the owner has looked.

The record's schema is narrower than the loop's vocabulary, so translate when recording and keep the loop-only fields (`pass_rule`, `reference_ids`, `metric`, `owner`, `views`) in the game's criteria file:

| Loop | `review-revision` record |
|---|---|
| criterion row | `kind` (`visual` for stills, `temporal` for motion rows), `subjects`, `required_scope` from the row's `views`, `environment` |
| `authoritative: engine` / `lab` / `either` | criterion `environment: native` / `lab` (or `blender` for Blender renders) / `any` |
| evidence `still`, orbit stills, `frame_strip` for a visual row | method `still` (a frame strip is several retained stills) |
| evidence `frame_strip` for a temporal row | method `scene_inspection` with `temporal_inspection: true`, `interval` and `duration_seconds` of the source clip, `context` naming the clip, and `actions` listing the frame times inspected |
| evidence `clip`, orbit and approach clips | method `clip`, with `media`, `interval` and `duration_seconds` |
| evidence `mesh_test`, `metric` | method `model_inspection`; retain the tool's output file, and put the tool, command, value and threshold in `location` |
| evidence `in_game` | environment `native` (method `still` or `clip`) |
| verdict `not_judged`, `not_applicable` | `inspection: not_run` with the reason and owner in `unknowns`; the report counts these as gaps |

A `metric`, `mesh_test` or `interactive_viewer` evidence method and a `not_applicable` state are not in the schema yet; until they are, the translation above is lossless for the facts but the report shows such rows as incomplete.

## Friction log

Keep one log per lane: date, area, what the kit made harder or could not express, and the improvement idea. Send it back to the kit owner; that is how the kit improves.

## Pre-critic checks worth running every round

These are cheap and catch builder bugs before a critic run is spent: loose-part counts and boundary edges before and after any reduction (`blender inspect`), near-black texels inside UV islands after a bake, a UV test pattern after writing any painted texture, a per-mesh diff against the previous round, and the runtime file size against its budget. See [Blender pitfalls](../../studio-blender/references/game-asset-pitfalls.md).

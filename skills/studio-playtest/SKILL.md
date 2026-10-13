---
name: studio-playtest
description: Play a game build with `studio playtest start` and `studio playtest collect` to find out how it actually feels, choosing between a human at the controls and a synthetic-input harness, and leaving a recorded session plus a re-runnable launcher behind.
---

# Studio playtest

Inputs: declared game root, host config, the expected engine SHA-256, and the one question this session is meant to answer. Output a recorded session under `artifacts/playtests/<label>`, a `relaunch` script the player can run again without this kit, and observations written as claims a person made. This skill decides how the game gets driven and what to watch; it does not issue the acceptance verdict.

Run the absolute [helper entrypoint](../../scripts/studio.py) with an explicit game root. Read [acceptance](../../references/acceptance.md) before writing any observation down, and [process and evidence lifecycle](../../references/execution-evidence.md) for what the receipts do and do not establish.

## Choose the input route first

Two routes exist and they prove different things.

**Ordinary controls, driven by a person.** The default, and the only route that establishes usability. Prefer it whenever a player can reach the thing under test in a minute or two of normal play: a spawn-adjacent slope, a door, a first-encounter creature, the feel of a jump. Reaching it by hand is not overhead — walking there is the test.

**A synthetic-input harness.** For routes a person cannot practicably drive by hand: a twenty-minute traversal, a flight path that must be flown identically twice, a timing run repeated across builds until a number stops moving, a seam ninety seconds of walking away from any spawn. Use `--session driven` with a script built from [the harness template](../../templates/playtest-harness.gd); [harness](references/harness.md) explains how to fill it in.

The boundary is the one [acceptance](../../references/acceptance.md) already draws: **script-injected input establishes wiring, not normal-input usability.** A harness that walks a character across a terrain seam without falling through it has shown the collision shape is there. It has not shown the walk feels right, that the camera stayed comfortable, or that a player would ever go that way. A harness result never substitutes for a human verdict, and a passing harness on a route no person has played is a reason to schedule a `handoff` session, not a reason to skip one.

## The canonical route

For evidence that will support a current-candidate review, pass
`--content-identity strict`. The default `cached` mode speeds repeat starts by
reusing file hashes from metadata and records that advisory identity method.
Its unchanged-content diagnostic cannot prove unchanged bytes; cached receipts
attach as identity `unknown`, retaining the observer's verdict independently.
Strict mode hashes every included file before and after play (or at collect).
Both modes prune excluded artifact/cache folders. Receipts record scan time,
file count, cache hits and method for each phase; see
[process and evidence lifecycle](../../references/execution-evidence.md).

The project owns a short ordered list of route steps a player actually walks from
the normal start: the canonical route. A run records it as `canonical_route` in
[feature-manifest](../../templates/feature-manifest.json), and every feature the
run claims gets a row there naming the step it appears on, the entry it is
reached through, and the script or scene that wires it in (`installed_by`).

A feature is accepted only when a person observed it on that route and its row
records `human_verdict: accepted` with the receipt linked. The verdict is
`pending` until a person has looked — that is the value the row is created with,
and it is the absence of a verdict — then `accepted` or `rejected`. An accepted
row's `content_digest` is copied from this session's own `playtest.json`, which
records the digest computed before the engine started: that is the build the
person walked through, and copying it is what binds the verdict to content
rather than to a moment. Never type one. Both blocking and attended sessions
write `exit.json`, with different later identity fields:

| Session | Later digest in `exit.json` | Change diagnostic |
|---|---|---|
| Blocking handoff/driven | `content_digest_after_exit` | `diagnostics.content_changed_during_session` |
| Attended, collected once | `content_digest_at_collect` | `diagnostics.content_changed_before_collect` |

Acceptance requires strict identity with `byte-hashed` methods at startup
(`content_identity_method`) and at the applicable later phase
(`content_identity_method_after_exit` or `content_identity_method_at_collect`).
Compare that later digest with `playtest.json`'s `content_digest`; attended
collection measures at collection, not at an observed exit. Differing or
unavailable digests, a true applicable change diagnostic, or metadata-cached/
unknown identity support no `accepted` row. The feature is observed again on a build that stayed still.
The row's digest must match the current final candidate's content and reviewed
scope; a historical session needs a fresh review. Neither matching hashes nor
a successful record checker grants human acceptance.
Observed in the scene where it was built is not that: an
isolated scene shows the feature runs, not that the game reaches it. Two features
that passed in their own scenes went into a handback unwired, because nothing in
the run had to name the step a player would meet them on. When a row's
`installed_by` points at a scene the route never enters, the feature is built and
not installed, and it is reported that way.

## Choose the session mode, and pay its cost

| `--session` | Use it when | What it costs |
|---|---|---|
| `handoff` (default) | The agent's last action before handing over the keyboard. | The command blocks until the player quits, so that session is the agent's whole turn. |
| `attended` | Maxim plays while the agent keeps desktop, voice or computer-use access to narrate, watch or take notes. | Nothing waits for the exit, so no return code, elapsed time or surviving descendant is ever observed for that run. |
| `driven` | A harness supplies the input and may declare `--result` files. | Bounded by `--max-minutes` and judged by assertions, which is the weakest evidence of the three about how the game feels. |

`--max-minutes 0` removes the cap and is legal only for `handoff` and `attended`, where a person decides when the session ends. A `driven` session has nobody at the controls and stays bounded. `attended` goes further: nothing waits for it, so a cap could only be written into the receipt and never applied, and a non-zero `--max-minutes` there is refused rather than recorded.

An `attended` session is completed by exactly one `playtest collect --label <label>`, run after the player says they are done. Calling `collect` repeatedly to find out whether the game has closed yet is polling, which the [overnight rules](../studio-director/references/overnight-run.md) forbid; the second call is refused rather than supported. Ask, or wait to be told.

Pass `--project <game>` and `--config <host config>` to both start and collect,
and the pinned `--sha256 <engine>` to start. In a bounded human review, handoff
uses a positive `--max-minutes` and an explicit `--cutoff-utc <operation deadline>`;
the earlier bound ends the owned run. Attended returns immediately, cannot enforce
a duration, and its cutoff gates admission only. The player or root desktop
operator must manually close the exact task-owned game window before collection;
collect does not close it, observe its exit or clean surviving descendants.
Use blocking handoff/driven or an owned `launch` when an enforced unattended
runtime bound is required. A driven/launch diagnostic never substitutes for
ordinary play or human acceptance; desktop operation stays with the root/operator.

Isolation is the default and throws away saves and settings between runs, which is right for a clean first look and wrong for anything about progression, settings or a save file. `--use-host-profile` plays on the real user profile and records `"profile": "host"`, so the receipt is never ambiguous about which one ran.

A session that will be started again, by an agent or by the person, belongs in a
`launch-profile.json` (copy [the template](../../templates/launch-profile.json))
and starts with `playtest start --profile <file>`: scene, session, renderer,
resolution, cap, passthrough and feature flags live in one project-owned file, an
identity manifest is verified before the engine starts, and `--check` verifies
without launching. Write the profile instead of a script that builds the
command; the receipt records the profile's path and hash, never the passthrough.

## What to look at on a first route

Watch for the things a screenshot cannot hold and a log will not mention.

The session runs the renderer and window size the project declares, not a pinned pair, because the renderer decides whether several of these appear at all. `--rendering-method` and `--resolution` override that deliberately, and the receipt records which of `project`, `override` or `default` applied — check it before filing a rendering defect, and say which renderer you saw it under.

- **Flicker while stationary, then flicker while walking.** They have different causes — z-fighting and shadow acne stand still, LOD and shadow-cascade seams only appear once the camera moves. Report them separately.
- **Grounded contact.** Feet meeting the surface, not hovering above it or sinking into it, on flat ground and on the steepest slope the character will accept.
- **Camera response.** Whether it lags, snaps, clips terrain on a descent, or pitches past what the player intended.
- **Whether the rendered art is the accepted art.** Runtime lighting, material and scale against the approved reference IDs; an asset that passed review in Blender can arrive wrong in the engine.
- **Discrete state events, not per-frame logging.** Log a landing, a slope rejection, a stream-in — things that happened once. Per-frame output buries the one frame that mattered and inflates the log this command captures.

Record what the session could not cover. A route walked for four minutes says nothing about minute twenty.

## Where this hands off

Return the run directory, the `relaunch` script path, the observations, and the question still open. Then:

| Next need | Read |
|---|---|
| The acceptance verdict, evidence pack and defect list | [studio-review](../studio-review/SKILL.md) |
| Input wiring, probe mechanics, `SceneTree` runners, frame-stamped assertions | [studio-godot](../studio-godot/references/testing-and-performance.md) |
| Filling in the harness template | [harness](references/harness.md) |

`ok` in a playtest receipt is run health: the engine ran, logged no errors and produced its declared results. It is never acceptance, and `acceptance` stays `not_established` in every mode. A playtest cannot be passed by a program.

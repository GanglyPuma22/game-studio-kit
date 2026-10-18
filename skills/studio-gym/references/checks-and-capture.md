# Gym checks and playtest capture

Read alongside [studio-gym](../SKILL.md). This is step 4: turning room questions into checks that run without a person, and recording the sessions a person plays so a moment in a video can be tied to a number.

## Three kinds of evidence, kept apart

| Evidence | Produced by | Establishes | Never establishes |
|---|---|---|---|
| Room check | A driven harness asserting the room's questions | The wiring and the threshold hold in this build | Feel, comfort, readability, mix |
| Metric snapshot | The same harness writing measured numbers | A tuning value moved or stayed put between builds | Whether the new value is better |
| Gym session | A person playing the gym route, HUD on, log running | How the verb feels at its edges | That the canonical route reaches it |

Report a room as **built**, **checked** and **observed** separately. A room that passes its check and was never played is checked, not observed. Each status records the `content_digest` and `content_identity_method` from the run's `playtest.json` and the receipts. Only a run started with `--content-identity strict` (method `byte-hashed`) makes a status current; a cached run, or one from an older digest, is stale until it runs again.

## Room checks

- One harness per room or per build stage, from [the harness template](../../../templates/playtest-harness.gd), filled in as [harness](../../studio-playtest/references/harness.md) describes. Drive the project's real input actions; never call movement functions directly.
- Each assertion is one room question, named for the claim: `climbs_44_deg`, `refused_46_deg`, `step_0_3_climbed`, `wading_slows_to_0_75`, `lands_on_20_deg_pad`.
- Assert by polling each physics frame until the condition holds or a frame limit passes. A fixed delay or a same-frame check breaks when the game moves its update later in the tick.
- A check that fails once and passes on a re-run is not a pass. Re-run it once to confirm, record both results, and treat a second failure as real. Do not mute or skip a check to get a clean run; a check that is wrong gets fixed or removed with a note in the plan.
- Run each room with `playtest start --session driven --script res://tests/<room>_harness.gd`. Only a driven playtest supplies the `--studio-playtest=<report>` argument the template writes to, so to run many rooms in one go, write one route harness that visits them all rather than batching room harnesses. `batch --plan <file>` and `launch` suit project-owned scripts that take their own result path through the passthrough and declare it with `--result` ([studio-godot](../../studio-godot/SKILL.md)). Do not poll for completion; these commands block until the engine exits.

Most checks can run in a minimal world (one room, the player, the system under test) and finish in seconds. Keep those the majority, and reserve the full-world route for the integration pass. A large catalogue of quick isolated checks with a few slow integrated ones is what kept a big studio's gameplay suite fast enough to run on every change ([sources](sources.md)).

## Metric snapshots and golden values

- The harness writes the measured numbers per question into its own report by returning them from the template's `_metrics()`, which the report writes under `metrics` next to `checks`; the kit supplies that report's path and hashes it into `exit.json`. A separate file is also fine if it is declared with `--result` at a project path outside the playtest run directory, such as `artifacts/gym-results/<label>.json`, because the kit refuses a result inside `artifacts/playtests/<label>/`. Numbers worth recording: jump apex, standing and running distance, time to top speed, stopping distance, highest step climbed, slope where sliding starts, landing impact, wading multiplier at each depth.
- Compare each number with the plan's `expected` and `tolerance`, then with the last accepted snapshot. Store accepted snapshots in the project (for example `tests/gym-golden/<room>.json`) with the build identity, physics backend and tick rate they were measured on.
- Update a golden value only when the tuning change was intended, in the same change that moved it, so the history shows why. A moved number with no tuning change is a regression report.

## One route through every room

Build stage 3 adds a driven route that teleports through every room in order, runs each room's steps and writes one report with every question's verdict and number. It is the gym's regression run: before a merge that touches movement, physics, water, audio or vehicles, run it and compare with the golden snapshots. It is also the cheapest frame-time sweep, because each room logs frame time on entry and exit.

## Input record and replay

Record a person's gym session as input events per physics frame with the seed and tick rate, including analog strengths and raw events (mouse motion, stick axes, trigger pressure) whenever gameplay reads them, and replay it on a later build. Replay turns "this felt different" into the same inputs producing a different trajectory. It only holds when the physics tick is fixed, random generators are seeded and gameplay code reads no wall clock; record any of those that is not true next to the recording. A recorder that keeps only digital action presses replays only digital routes faithfully; say so when that is all it keeps.

## Human sessions on the gym

- Start with `playtest start --session handoff` for one sitting, or `attended` when the agent keeps watching or taking notes. Use the gym's launch profile so the receipt names the flag and build.
- Keep the metrics HUD on and the event log running. Capture video at the game's real resolution and renderer.
- Lining up a video with the log works through the logged events (landed, slope rejected, entered water), each stamped with physics frame and time. Agents reading a video see sampled stills: measurements from a still camera are reliable, judgements about a moving camera are inferred. Prefer an in-game debug view and a synced log over reading motion off frames.
- Write what the person said as their claim, with the room and question it concerns ([acceptance](../../../references/acceptance.md)). A comment such as "the 40° ramp feels sticky" becomes a question for the plan, not a tuning change on the spot.

## What goes back into the plan

After each round update the gym plan: room status (built, checked, observed), measured numbers, new gaps with the room that exposed them, keys added to the registry, and the open question. A gap closed by a game change records the change and the check that now proves it.

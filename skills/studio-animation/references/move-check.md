# Move check: the standard

A move check gives every recorded character move a pass or a fail before a person looks at it.
It measures the move the way the game draws it, so it catches what a clip, a mocap take, a refit,
a procedural pose or a new skin turns into on the real body. This file is the standard part: which
checks exist, which ones block, how a move is sampled, how known problems are carried, and where
the check is enforced. Each game keeps its own recorder, limits, joint ranges and accepted
exceptions. How to animate and fix until the check passes, and the stop rule for fix loops, are in
`generated-mesh-skin.md` (beside this file, added with kit PR #71). Where the two differ on a number, this file wins.

## When it runs

Run it on any change that can move a recorded body: the rig or its rules, a skin or its weights,
a clip or its import, the character's body or kit code, shared animation code, or motion tuning.
An agent iterates against it until the moves it changed pass. Only then does the person see
them. The person should never be the first to find a defect the check could have measured.

## The recording contract

The check is only as good as the recording. A recorder must:

- **Play the move in the game.** Use the real character and the same driver that makes the review
  takes, so the checked move and the shown move are one recording.
- **Record what is drawn.** Take each sample after the frame is drawn and after every clip, video
  pose or override has applied. Sampled earlier, the body has already moved that tick but the rig
  has not posed on it, and every fast vertical move shows false floor sinks. A rule check that runs
  inside the animation step, before overrides, is not what the player sees.
- **Record both ticks.** A game that runs 60 ticks a second and is recorded at 30 keeps every
  second tick, so a one-tick defect on the other tick is never measured, yet the player sees it.
  Record each move twice, once on each tick of the pair. A move carries every problem from either
  recording, keeping the worse value where both have it. A recording with only one tick is a quick
  look, never a pass. In one pilot, 15 of 19 moves were clean on the sampled tick and only 8 on both.
- **Record a rest sample.** Record the settled character before the move's input. Foot sole
  heights and "already wrong at rest" both come from it. A recording without one is blocked.
- **Record the gameplay side.** For each strike, record the gameplay hand or mouth and the tick
  contact happens. Latch the hand on the tick the strike leaves its active phase, not on a hit
  list that some contacts never append to.
- **Cross-check the skin.** If the checker poses the skin itself, compare it on some frames with
  the engine's own posed mesh. Block the move if they disagree by more than about 2 cm.
- **Fail loudly.** A recorder that printed a script error, exited nonzero, or wrote a move with
  no trace is blocked. It is never "not checked" and never a pass.

## Checks

Lengths are for a body about 10 m tall and scale with the body. The limits are starting values;
a game tunes them per character from moves the person approved.

| Check | What it catches | Class | Starting limit |
|---|---|---|---|
| feet-sink | a drawn foot under the floor | note; blocker past 3x | 0.10 m (0.30 m blocks) |
| feet-float | a planted foot hovering | note | 0.25 m |
| foot-slide | skin touching the floor sliding along it | note | 1 m/s for 2 frames |
| body-sink | any non-foot skin under the floor (dead bodies included) | blocker | 0.15 m |
| foot-turn | a flat foot turned from the hips | blocker | 45 deg for 3 frames |
| stretch | skin edges pulled past their rest length | note | 1.8x |
| tear | a seam between neighbouring parts opening | blocker | 0.15 m |
| fold | skin triangles turned over | note | 40 triangles |
| crossing | a limb's capsule through the trunk, head or other leg | blocker | 0.3 of the two thicknesses |
| overlap | skin of one part inside the rest of the posed mesh (winding number) | blocker | 0.12 m, however brief |
| joint-range | a joint's swing or roll from rest past its range | blocker | per character, from approved moves |
| joint-speed | a joint turning faster than a body can (a one-frame pop) | blocker | 1500 deg/s |
| twist-speed | a limb rolling fast about its own length (an elbow or knee flip) | blocker | 720 deg/s |
| hit-hand | the drawn fist or jaws away from the gameplay contact point | blocker | 1.5 m within 0.1 s |
| hinge | an elbow or knee bending the wrong way, on the drawn pose | note | 10 deg |
| head-aim, balance, jerk, weight | the head off its target, centre of mass off the feet, limb or hip acceleration | note | 75 deg; 0.8 m; 3000 and 450 m/s2 |

Roll is undefined for a limb swung nearly opposite its rest (more than 135 degrees), so don't
measure joint-range roll there. twist-speed still catches a flip.

**Blockers are the same for every character from its first recording.** They are what a person
sees at once on pause: a tear, a limb through the body, skin inside skin, anything under the
floor, a foot or joint turned past what a body does, a pop, and a strike that misses its own
hit point. A new character starts with joint-range quiet until its ranges are set from moves the
person approved. Its other blockers apply from day one.

**Notes** depend more on style and size. Each one becomes a blocker, or gets a tighter limit,
only after it has been run against moves the person judged on that character.

Every stretch, tear and fold finding should name where to fix it, worked out from the same
recording:
- **The model or its bind:** the fault is already there at rest.
- **Weights:** the joint under the fault has turned less than about 50 degrees from rest.
- **The pose:** the joint is near its range.

## Verdicts and known problems

- **PASS:** no problems on either tick.
- **KNOWN:** only problems the character's known list already has, none worse (10% slack). It may
  be shown to the person, marked "known".
- **FAIL:** a new problem, a worse one, or any blocker. It is never sent unless the person asks
  for that one move.
- **BLOCKED:** the recording cannot be trusted (no rest sample, one tick only, skin disagreement,
  recorder error). It is not a pass.

The known list is a ratchet. Record today's problems per move, blockers included. Fixing a cause
and re-taking the list shrinks it, and nothing loosens it silently. Blockers stay listed so the
CI gate can tell an old blocker from a new one. They still hold the move from review. Count the
idle's own defects once, as the body's (a character standing in the floor), not again on every
move.

## Standard vs per game

| Standard (this file) | Per game, in its repository |
|---|---|
| The check list, what each catches, which block | The recorder for its engine and characters |
| Both ticks, sampled after the draw, rest sample, gameplay contact tick | Limits per character, per move and per character-move, each loosened layer with its reason |
| PASS / KNOWN / FAIL / BLOCKED and the ratchet | Joint ranges per character, set from approved moves |
| Blockers never sent; iterate until pass before the person looks | Accepted exceptions, quoting the person's OK and date |
| The three enforcement points below | The known list per character and move |

Loosen a limit only with the person's OK, written as that layer's reason. When the person finds a
defect by eye that the check passed, first write the check that would have caught it, make it a
blocker if it is visible on pause, then fix the move.

## Where it is enforced

1. **At the review send.** The tool that sends takes for review records both ticks and holds every
   move that fails. Sending a failing move marked as failed needs the person's word for that move.
2. **In CI.** A change that can move a character's recorded moves selects a gate step. The game
   keeps a path-to-character map: shared animation code moves every character, and a character's
   own body, art or skin tools move only it. The gate records those characters on both ticks and
   fails on any move that is blocked, or has a problem the **target branch's** known list does not
   have, or is worse than listed. Read the bar from the target branch, so a change can't lower it
   by editing its own copy. Run the gate alone, after the other checks: recordings are heavy, and
   timing-sensitive tests flake beside them.
3. **In the written rules.** The repository's agent guidance says to iterate until pass, link the
   check report in the PR, never absorb a new problem into the known list, and loosen limits only
   with the person's OK. The PR template has a line for the report.

## Checklist

- [ ] Recorder samples after the draw, on both ticks, with a rest sample and the contact tick.
- [ ] Skin cross-checked against the engine; recorder errors block.
- [ ] Every blocker in the table on from the first recording; joint ranges from approved moves.
- [ ] Known list re-taken on both ticks, blockers included; bar read from the target branch.
- [ ] Review send and CI gate both refuse a failing move; rules written in the agent guidance.

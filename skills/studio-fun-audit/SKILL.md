---
name: studio-fun-audit
description: Name the kind of fun each role in a game is promised in one word that is not the word fun, then score a mode, feature or respawn rule against those named kinds, the four legs of dead time, the death-readability window and the death-screen progress pattern, from playtest evidence rather than intuition.
---

# Studio fun audit

Inputs: the project record or work card, the roles a player can take, the candidate modes, features or rules under question, and every playtest report and recorded observation that exists ([studio-playtest](../studio-playtest/SKILL.md)). Output a [fun audit record](../../templates/fun-audit.json): one named fun target per role, a score per candidate and per role, each score marked `evidence` or `hypothesis`, the weakest leg of every dead state, and the smallest experiment that would move the score that matters most. This skill decides what a design is for and whether a candidate serves it. It builds nothing and issues no acceptance verdict.

The word fun in a design document describes nothing, because every reader pictures a different game. The audit replaces it with a named kind from a shared vocabulary ([kinds of fun](references/kinds-of-fun.md)), grounded in one or two concrete mechanics, so a mode decision is argued from what the game asks each player to come back for, not from bot win rates or taste.

## Rules that make an audit trustworthy

- **One primary kind per role, grounded in a mechanic.** Each role, and the team where teams exist, gets exactly one primary kind and at most two secondaries. The verdict rests on a mechanic the player meets ("the death screen shows which boss phase you reached"), never on a genre label ("it is a roguelike"). A target that cannot name its mechanic is a wish, and it is recorded as `hypothesis`.
- **The player feels first.** Mechanics produce dynamics, dynamics evoke feelings, and the designer controls only the mechanics. A feeling cannot be shipped, only tested for, so every score is `evidence` (a person reported it on a recorded session or in a structured playtest report) or `hypothesis` (the auditor expects it), and the record says which. The owner's playtest judgment outranks bot data; bot numbers are balance evidence, never fun evidence.
- **Asymmetric play has two budgets.** Where roles differ, every ability and every rule is scored twice: fun to use and fun to face. The published reason asymmetric player-versus-player modes get cut late is that reconciling both sides for every ability turned out to be a monumental task, so an audit that scores only the acting side is half an audit.
- **Dead time is a defect until the record shows otherwise.** Every state in which a player cannot act is scored on the four legs in step 3. "Players will accept it" is a hypothesis.
- **Fragile on one key.** A mode that touches only one of the four keys (hard, easy, people, serious fun) is fragile; the player research behind the keys found best-sellers tend to touch three. Record the count per role.
- **Generic vocabulary, project names.** The record uses the project's own role, mode and mechanic names; the kinds, keys and legs stay as this skill names them so audits of different games compare. Nothing in this skill is a verdict about any particular game.

## Step 1: name the fun targets

Write one row per role, and one for the team, into the record before scoring any candidate:

| Field | What goes in it |
|---|---|
| `role` | The role as the project names it (a playable side, class or seat, or `team`) |
| `primary` | One of `sensation`, `fantasy`, `narrative`, `challenge`, `fellowship`, `discovery`, `expression`, `submission`; `competition` is accepted where the paper's own example uses it |
| `secondary` | Up to two more kinds, or none |
| `mechanic` | The one or two mechanics the primary rests on, as the player meets them, with `path:line` when a number or rule lives in code |
| `keys` | Which of `hard`, `easy`, `people`, `serious` the role touches |
| `status` | `evidence` with the session or report, or `hypothesis` |

Targets come first because a candidate that wins a playtest or a bot balance pass while missing a role's named kind is the wrong winner, and that is visible only when the target was written before the contest.

## Step 2: score each candidate, per role

For every candidate mode, feature or rule, and for every role, answer in the record:

- **Delivery.** Which named mechanic delivers the role's primary kind under this candidate, and does the candidate keep, strengthen or remove it? A format that takes a role's core verb away for part of the match (a spectating player whose primary kind rested on a movement verb) scores `absent` for that time, whatever else it offers.
- **Use and face.** For each ability or rule, is it satisfying to use, and is the counterplay readable and available to whoever faces it? Two scores, never one.
- **Required fellowship.** Which mechanics require another player rather than allow one? Count them. The test case is a co-operative game with no solo mode and no artificial partner, whose asymmetric abilities force interdependence. Cooperation that is merely permitted is not fellowship.
- **Visible contribution.** Can a player see their own contribution, not only whether the team won? A shipped team game that bet everything on the team result and downplayed individual contribution is a regret its director stated publicly.
- **Efficiency and fantasy.** Is the most efficient thing to do also the most fun thing to do, and does the behaviour the rules induce fulfil the role's fantasy? Healing by retreating failed this test in a shipped action game whose fantasy was pressing forward; healing by advancing replaced it.
- **Keys.** How many of the four keys the candidate touches for this role.

Each answer carries `evidence` or `hypothesis` and the report or session it rests on.

## Step 3: score every dead state on the four legs

A dead state is any time a player cannot act: dead and waiting, respawning, between rounds, walking back from a spawn. Per candidate and per role, mark each leg `present`, `weak` or `absent` from playtest reports, using the shipped examples in [respawn and dead time](references/respawn-and-dead-time.md):

| Leg | Question | `present` looks like |
|---|---|---|
| 1 Cap | How long is one dead stretch, and what share of a match is spent in one? | At or under the worst shipped one-life rounds (two to three minutes), and a small share of the match |
| 2 Job | What can the dead player do that changes the outcome? | Information (cameras, pings, calls), planning (economy, next-round decisions) or rescue (bringing a teammate back) |
| 3 Readability | Did the death read as the player's own mistake, with time to recognize, assess and react? | The project's readability window (step 4) was met on most recorded deaths |
| 4 Stakes | Does spectating turn into drama? | High lethality and one life make a late outnumbered stand the emotional peak, and the dead are its audience |

Respawns fix leg 1 outright and can fix leg 4 when every respawn spends a team resource. They do not by themselves give the dead a job or make deaths readable, so any format that keeps waiting at all keeps legs 2 and 3 as open questions. Name the weakest leg per candidate before designing anything new, and treat a whole-round wait with nothing to do as a defect, not a neutral default.

## Step 4: set and measure the death-readability window

A death is readable when the player had time to recognize the threat, assess it and react. A shipped action role-playing game tuned full health to death at roughly three to five seconds for that reason; deaths faster than the window read as random and feel unfair. The project sets its own number, puts it on a tuning slider, and measures: of the deaths in recorded sessions, what share gave the victim at least the window through telegraphs, sound cues and approach visibility? If most deaths are sub-second surprises, fix telegraphs before mode surgery, because an unreadable death spends the player's patience in every format.

## Step 5: spec the death-screen progress pattern

On every death, before the respawn timer or the spectate view, show the player what this life achieved: damage dealt, objective progress, the phase of the fight reached, distance covered, resources earned. A famously hard game's death screen shows a progress bar with the boss phase reached, and that manufactured micro-victory is what turns a retry into progress instead of punishment. The pattern is format-agnostic and cheap. Spec it from data the game already tracks, behind a default-off flag with sliders for what it shows and how long, and list data that does not exist yet as a gap rather than inventing it.

## Step 6: write the experiment, not the opinion

Every `hypothesis` that bears on a mode decision gets the cheapest branch prototype that would turn it into evidence, recorded with what the playtest must measure (dead time per death and per match, what dead players did, share of readable deaths, keys touched) and what result would change the recommendation. Prefer an experiment that separates two explanations, such as "the no-respawn rule is wrong" from "the wait was empty and the deaths were unreadable", over one that tests a replacement rule, because the replacement can win for the wrong reason. Mode changes stay on their own branch with their own playtest build until the owner decides; every new mechanic gets sliders; the structured playtest report is the evidence channel.

## Checklist before handing back

- Every role has one primary kind, a named mechanic and a status.
- Every candidate is scored per role, use and face separately, keys counted.
- Every dead state is scored on all four legs and its weakest leg is named.
- The readability window is set and measured, or marked `not_run` with the sessions it needs.
- The death-screen progress display is specced, or its missing data is listed as gaps.
- Each hypothesis that matters has an experiment with a measurement and a decision rule.
- The record is written in the [template's](../../templates/fun-audit.json) shape and the work card's decided, proposed and open ledger is updated.

## Where this hands off

| Next need | Read |
|---|---|
| The vocabulary, its limits and six worked one-word verdicts | [kinds of fun](references/kinds-of-fun.md) |
| Shipped respawn and no-respawn designs behind the four legs | [respawn and dead time](references/respawn-and-dead-time.md) |
| A complete audit of a symmetric mode and of an asymmetric one | [worked examples](references/worked-examples.md) |
| An encounter brief for a feature the audit asks for | [studio-game-design](../studio-game-design/SKILL.md) |
| Running the sessions that turn a hypothesis into evidence | [studio-playtest](../studio-playtest/SKILL.md) |
| A room that measures a telegraph window or a spawn walk time | [studio-gym](../studio-gym/SKILL.md) |
| Acceptance of a feature once it is built | [studio-review](../studio-review/SKILL.md) |
| Where every claim above comes from | [sources](references/sources.md) |

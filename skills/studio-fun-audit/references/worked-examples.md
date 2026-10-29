# Worked examples

Two audits in the record's shape. The first is a shipped co-operative game, scored from its published design and from Cheng's verdict. The second is an invented asymmetric team mode built from the patterns in this skill; every number in it is illustrative, and its scores show how `evidence` and `hypothesis` are kept apart. Neither is a verdict about any real project.

## Example 1: a two-player co-operative platformer (It Takes Two)

**Fun targets**

| role | primary | secondary | mechanic | keys | status |
|---|---|---|---|---|---|
| player (either seat) | `fellowship` | `narrative` | No solo mode and no artificial partner; each level gives the two seats different abilities that only work together (one hammers the nail the other placed) | people, easy, hard | `evidence` (published design, reviews, Cheng's verdict) |
| pair | `fellowship` | `discovery` | Every new level replaces both ability sets, so the pair rediscovers the dependency | people, easy | `evidence` |

**Candidate scored: the shipped game**

- Delivery: the dependency mechanic is present in every level; `present`.
- Use and face: not applicable, no opposing role.
- Required fellowship: every traversal and boss mechanic requires the other seat; count is "all of them". This is the bar the skill means by required rather than allowed.
- Visible contribution: each seat's ability is distinct, so each player can see what they did; `present`.
- Efficiency and fantasy: the efficient play is to coordinate, which is the fantasy; `present`.
- Keys: three of four.

**Dead states:** a fallen player respawns beside the partner within seconds; leg 1 `present`, leg 2 `present` (the partner keeps acting and the fallen one is back before a job is needed), leg 3 `present` (hazards are telegraphed platformer hazards), leg 4 not sought. Weakest leg: none material. Death-screen progress: not needed, the retry is immediate.

## Example 2: an invented asymmetric siege mode

A team of five small, fast, grapple-moving players (call them runners) defends a wall from a team of five player-controlled colossi (call them walkers). The project is deciding between a one-life round format and a respawning siege format. Playtest reports exist for bots in both and for one human session of the one-life format.

**Fun targets**

| role | primary | secondary | mechanic | keys | status |
|---|---|---|---|---|---|
| runner | `challenge` | `sensation` | Grapple traversal and the counterplay timing of attacking a walker's weak moment; the grapple feel is the sensation source | hard, easy | `hypothesis` (one human session; the player named the movement as the reason to come back, which is one report, not a pattern) |
| walker | `fantasy` | `challenge` | Being the enormous thing: scale, weight, breaking the wall; skill-based counterplay against runners | hard, people | `hypothesis` (no human walker session yet) |
| team | `fellowship` | `competition` | Coordinated takedowns of a walker, and the shared wall as an objective | people | `hypothesis`; no mechanic yet requires a second runner, so this target is currently a wish |

**Candidate A, one-life rounds (first to seven)**

| role | delivery | use / face | required fellowship | visible contribution | efficiency and fantasy | keys | status |
|---|---|---|---|---|---|---|---|
| runner | `present` while alive, `absent` while dead: the core verb is traversal and a spectating runner has no traversal | abilities: use `present`; face (as a walker) `hypothesis` | none required | round win only; nothing inside a lost round | efficient play is hit-and-retreat, which matches the fantasy | hard, easy | `evidence` for the dead-time absence (human session report: "waiting after dying is the worst part"), `hypothesis` elsewhere |
| walker | `present` | use `hypothesis`; face: a runner facing a sweep that lands in under a second reported it as unreadable | none required | round win only | `hypothesis` | hard | mixed |

Dead states: a dead runner sits out the rest of the round. Leg 1: round length is short (under a minute in bot runs) so `present` per stretch, but the share of a first-to-seven match spent dead is high, so `weak`. Leg 2: `absent` (no economy, no buy phase, no camera job, and fight information decays in seconds in a movement duel). Leg 3: `weak` (one unreadable death reported; share unmeasured). Leg 4: `weak` (one-against-many stands happen but the dead have nothing to watch for). **Weakest leg: 2.**

**Candidate B, respawning siege (respawn timers, shared walker respawn pool, wall with staged health)**

Dead states: runner respawn around ten seconds, walker fifteen seconds from a shared pool. Leg 1: `present` (bot runs show five to eight seconds dead per death). Leg 2: `absent` still, the wait is short but empty. Leg 3: unchanged, `weak`. Leg 4: `present` for walkers (each respawn spends a team resource) and `weak` for runners (free respawns remove the stakes of a runner death). Micro-victory device: staged wall damage persists between rounds, which is the progress-bar pattern at team scale. **Weakest leg: 2 for runners, 3 for both.**

**What the matrix makes visible**

- Sensation is under-weighted in both candidates: the movement feel is the invitation (the first five minutes and the store page) and challenge is the retention engine, and neither candidate features the former.
- Fantasy carries the walker and nothing carries runner fantasy; if walkers bore first, check fantasy and expression (kit identity) before touching numbers.
- No mechanic requires a second runner, so the team's fellowship target is unmet in both candidates. The next design question is which takedown step could require two players.
- The death screen is an unbuilt surface in both candidates, and the wall's stage data already exists for it.

**Experiments, cheapest first**

1. Readability pass on existing recordings: share of runner deaths with at least the project's window (set at three seconds on a slider). Changes the recommendation if most deaths are sub-second: fix telegraphs before choosing a format.
2. Dead-runner job prototype on the one-life branch: free camera plus pings on walker position and wall state, A/B against plain spectating, measuring dead time, what the dead did, and the owner's report. Separates "no-respawn is wrong" from "the wait was empty".
3. Death-screen progress on both branches, default-off, showing damage dealt this life and the wall stage.
4. Only then the mode decision, judged against the targets table, with what would have to be true in a playtest for the runner-up format to win.

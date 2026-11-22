# Pilot audit: where 25 versions went

The evidence behind the stages in [studio-character-design](../SKILL.md). One game, four large non-human characters built from generated bodies in November 2026, audited on 2026-11-22 from the model library's own records after the owner asked why one of them had reached version 24. Numbers are counts from those records; "avoidable" is the auditor's judgment.

## Counts

| Character | Library versions | Move takes |
|---|---|---|
| Ice giant (the pilot) | 25, of which 20 in the 16 days after the redesign began | 574 in those 16 days |
| Rock giant | 6 | 386 |
| Bell giant | 4 | 98 |
| Plant giant | 2 | 231 |

The pilot is the one whose look went through repeated final-art rounds, still open at the audit. The plant giant never had a final look pass, so the method built on it did not cover that stage. The pilot also carried 58 look settings (41 for its mane), five shader variants only it used, and a 283-file pull request for its last look.

## Where the pilot's versions went

| Versions | What they were |
|---|---|
| 1 to 5 | The older hand-built body and syncs |
| 6 to 11 | Generator and reduction bake-off; the owner picked a remeshed body |
| 12 to 13 | First versions in the game. Version 13 is the one the owner kept pointing back to |
| 14 to 16 | A dark core, asked for and then judged too intense |
| 17 to 19 | Colour passes back toward version 13's blues |
| 20 to 23 | A snow layer, then three re-sends in two hours for code-review fixes |
| 24 to 25 | Lines redrawn (rejected as scribble, eyes in the wrong place), then a fix |

Of the 12 versions after version 13, about 8 were avoidable: they asked a look question at production cost, or re-sent a look nobody had accepted.

## Findings and the stage each one produced

1. **No drawn target for "final".** The concept fixed the shape only. Everything else was found by building and reacting, and the owner said afterwards that it had been an interactive process and they had not known what they wanted. Produced the [target sheet](target-sheet.md), and its rule that exploring happens there.
2. **Look ideas were built at production cost.** Each idea got a shader, a bake tool, settings, a library version, 22 to 30 moves, a test run and two code reviews before the owner saw it. Produced the [look bench](look-bench.md) and rule 4.
3. **The review picture differed from the game.** Five mismatches between the model viewer or a fallback renderer and the build in two weeks, while requests for approval still led with viewer links. Produced rule 3.
4. **The method changed every round with nothing beside it.** Lines were reworked four times after version 13 and the mane seven ways, with no side-by-side against the version that worked. Produced rules 5 and 6.
5. **The body was the first one generated and was kept.** Concept stance, arms down, mane fused in, a remesh service's automatic texture layout in 6,249 pieces. Blender was later used for its skin weights only; the mesh and layout stayed. The owner believed the body had been rebuilt and laid out again, which it had not. Produced the [rig-fit picture and report card](body-report-card.md), rules 8 and 9, and the habit of saying in plain words what was and was not redone.
6. **Agreed fixes were not carried out.** Two weeks earlier a review had recommended flat paint for the other bodies, a one-page style standard and final approval in a build, and all three were accepted. The flat paint was built on a branch and never merged, the style page was never written, and no look was approved in a build until the day of the audit. Produced rule 2 and the run record's design gates.

## What worked and stays

- The generated body's shape: the owner picked it and kept pointing back to its first version in the game.
- One skin on the uncut body with automatic weights ([generated mesh skin](../../studio-animation/references/generated-mesh-skin.md)).
- The move check as a gate before anything is shown ([move check](../../studio-animation/references/move-check.md)).
- A side-by-side picked in one round whenever one was offered: the rock giant's paint method was picked from a single two-row picture.

## Not yet proven

The seven stages are a proposal from this audit. At the time of writing no character has been through the target sheet or the look bench, and the round budgets are estimates. The first character that runs them should record its real round counts here and correct the budgets.

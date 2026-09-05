---
name: studio-director
description: Coordinate a bounded game-scene production task through the studio package, selecting internal skills, capabilities and evidence for a concrete player outcome.
---

# Studio director

Start from the next player-facing outcome. Inputs are the declared game directory, project record, work card, approved references and existing candidate. Preserve established decisions and session authorization. If inputs are thin, draft a small work card from available facts and expose only material open questions; continue independent work.

Resolve this file's location to the package root (`../../`), then read [portability](../../references/portability.md). Run the absolute [helper entrypoint](../../scripts/studio.py) with an explicit game/output root. Do not assume the current directory is this package or write into its cache. Read [production contracts](../../references/production-contracts.md) and the relevant capability row in [tool routing](../../references/tool-routing.md).

1. Read or create the [project record](../../templates/project.json) and [work card](../../templates/work-card.md). State scope, owner, time/provider/iteration budget, reference identities, normal-input route and the question the candidate must answer.
2. Run `doctor --config <host-file>` offline. Distinguish installed tools from tested operations, credentials from live entitlement and host computer use from a Python report. `setup` produces missing actions; reuse working tools and preserve completed assets.
3. Route only the current production need to the internal entrypoint below. A session may perform several roles sequentially. Delegation is optional, follows the user's/host's authorization and never creates competing writers or desktop operators.
4. Produce editable source and explicit runtime outputs with hashes. Review import and behavior before multiplying asset variants. When an observed defect is inside the work card, make a bounded correction and rerun the affected check. Stop ambiguous paid submissions, exhausted budgets or missing required user decisions; continue unrelated local work.
5. Build a candidate with source/content/workflow identity. Route to review. Report separate visual, interaction, motion, audio and performance results, the concrete artifact location and remaining decision. Never promote provider completion or a technical fixture into artistic acceptance.

| Task | Read next |
|---|---|
| Gameplay action, story/companion state | [studio-game-design](../studio-game-design/SKILL.md) |
| Reference/style contract and concept comparison | [studio-art-direction](../studio-art-direction/SKILL.md) |
| Modeling, material, render, GLB | [studio-blender](../studio-blender/SKILL.md) |
| Generated asset candidate | [studio-meshy](../studio-meshy/SKILL.md) |
| Heightfield, authored terrain, Gaea | [studio-terrain](../studio-terrain/SKILL.md) |
| Nonhumanoid rig, clips, transitions | [studio-animation](../studio-animation/SKILL.md) |
| Effects, ambience, foley, voice, music | [studio-audio](../studio-audio/SKILL.md) |
| Import, runtime composition and bounded wiring | [studio-godot](../studio-godot/SKILL.md) |
| Native appearance/input/motion/mix acceptance | [studio-review](../studio-review/SKILL.md) |

First use: follow [Windows setup](../../docs/setup-windows.md) or [Linux setup](../../docs/setup-linux.md). A functional, original [harbor example](../../examples/harbor-pocket/README.md) works independently of any private game. Return a work card, capability result, candidate pointer and decision ledger that another session can consume without this conversation.

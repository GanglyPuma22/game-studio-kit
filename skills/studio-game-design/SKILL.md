---
name: studio-game-design
description: Specify a playable encounter, gameplay feedback and narrative or companion state for a bounded game scene before wiring it into the engine.
---

# Studio game design

Inputs: work card, intended player experience, existing game interfaces, approved story facts and exact art references. Output a compact encounter brief with an action/state/feedback table and a decided/proposed/open ledger. Use [production contracts](../../references/production-contracts.md).

Describe what the player sees first, what ordinary action they can take, why it is legible and what changes. Name entry conditions, interaction range, active/cooldown/reset states and failure feedback. Include the uninteresting but necessary cases: walking away mid-response, repeated input, entering during a loop, and loading without an optional provider service.

Separate gameplay authority from presentation. State who owns the ecological or puzzle state and which animation/audio events observe it. A voice backend does not define a fictional companion's identity. Record what the companion knows, when it speaks, who can interrupt it and how silent/unavailable voice behaves; do not invent private canon.

Use an event table such as `idle + E within range → responding → one clip + one cue → idle`. Pin ordinary camera, player speed/scale, affordance and expected duration before suggesting extra mechanics. Preserve existing project interfaces when implementing; engine migrations and broad physics changes need their own scope.

Propose only the smallest encounter that answers the work card's question. Distinguish a functional cue from a final voice and a procedural object from an approved production design. Hand motion requirements to [animation](../studio-animation/SKILL.md), cue/event mapping to [audio](../studio-audio/SKILL.md), and decided state/feedback to [Godot](../studio-godot/SKILL.md). Return measurable acceptance questions, not an expanding lore document.

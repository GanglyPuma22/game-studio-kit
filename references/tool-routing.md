# Select a route for the operation

| Need | First useful route | Escalation / handoff |
|---|---|---|
| Scope, action, story feedback | studio-game-design | Ask only for a material unresolved product decision |
| Which kind of fun a role is promised; a mode, respawn rule or dead-time audit | [studio-fun-audit](../skills/studio-fun-audit/SKILL.md) | Every score is evidence or hypothesis; the owner's playtest judgment outranks bot data |
| Reference fidelity and asset family | studio-art-direction | Use the host's available concept tool when authorized; record reported model only |
| New model or look-changing remodel, when `art_pipeline.concept_required_for` lists it | studio-art-direction [concept and free base](../skills/studio-art-direction/references/concept-and-bases.md) | Owner approves the concept; CC0/CC-BY base check before Blender or a paid generator. Without `art_pipeline` this is a recommendation, not a gate |
| Critic rounds on a visible asset | studio-review [critic loop](../skills/studio-review/references/critic-loop.md) | Round cap and owner look; `review revision` records the chain |
| Deterministic mesh, material, scale, render | studio-blender background scripts | Native app inspection for composition/cleanup; optional matched MCP pair |
| Reference-guided candidate generation or model preprocessing | User-selected, capability-verified [studio-tripo](../skills/studio-tripo/SKILL.md) or optional [studio-meshy](../skills/studio-meshy/SKILL.md) | Local Blender first for trivial repairs; Tripo is a workflow only, with no `studio tripo` command |
| Nonhumanoid deformation | studio-animation in Blender | Humanoid provider rig only after its separate eligibility check |
| Heightfield | studio-terrain local generator | Gaea UI graph plus installation-verified build recipe |
| Timed functional cue | studio-audio local PCM | ElevenLabs effects/speech/music with rights and budget |
| Generated sound effects or instrumental music | studio-audio Colab models route (Stable Audio Open, ACE-Step through studio-cloudrun `model-run`), after the person's go for units | ElevenLabs effects/music with rights and budget |
| Import and gameplay response | studio-godot | Ordinary player-input native review |
| Gameplay gym: verb inventory, measured rooms, room checks | [studio-gym](../skills/studio-gym/SKILL.md) | Gym observation is wiring and feel at the edges; canonical-route play still decides acceptance |
| Free textures, HDRIs, base meshes or kits from public CC0/CC-BY libraries | [studio-assets](../skills/studio-assets/SKILL.md) | Fetch only what the asset needs; the ledger records licence and hash; a found asset is still reshaped, restyled and qualified |
| Unattended capture on a GPU (clips, stills, build-vs-build pictures) | [studio-cloudrun](../skills/studio-cloudrun/SKILL.md) `where: here` (software Vulkan, free) | `where: colab` through the queue service, only after the person's typed go; never trust its frame timings |
| Continuous recording and video analysis | studio-review [operational loop](../skills/studio-review/references/validation-loop.md), explicit FFmpeg and Gemini adapters | Native host permission and original-fixture detection remain separate gates |
| Visual/motion/audio verdict | studio-review and actual host tools | Precise native/manual handoff if computer use/capture/listening unavailable |

`doctor` is offline-first. An executable's `ready` means it answered a version query; operations remain unverified until executed. Credential presence is not authentication, entitlement, balance or provider readiness. The helper always reports host computer use as unverified: the active agent must inspect its actual tool list and perform a bounded native app operation to establish it.

Each output has one writer. Only one operator controls the visible desktop. Delegation is optional and follows host/user authorization; the seventeen skills are not seventeen persistent agents. Save the editable source before a mode switch and track who owns any launched process. Do not reuse another project's environment assumptions.


| Concrete request | Staged reads and advancement |
|---|---|
| Refine a reef toward an approved reference | Director decision → art-direction/asset family → Blender one specimen → Godot/review; record close/play comparison before replication |
| Repair ship legs cutting ground | [Source/contact](source-and-contact.md) → Blender source authority → Godot/review; test all complete pad footprints against final base and shelves |
| Compare Fish and ElevenLabs speech | Audio speech → only those two profiles → shared preparation/listening; same intent, separate voices, explicit combined budget |
| Improve surf loop | Audio ambience/preparation → Godot import → runtime listening; zero budget means existing/local original, no Fish speech read |
| Animate a nonhumanoid | Animation → needed Blender rig/export → Godot transitions → motion review; no default humanoid provider |

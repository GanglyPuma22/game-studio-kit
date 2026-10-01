---
name: studio-animation
description: Prepare a nonhumanoid Blender rig or deformation system, author named game clips and validate loop, stress-pose and runtime transition behavior.
---

# Studio animation

Inputs: editable mesh and dimensions, intended motion language, rig eligibility, rest/stress poses, clip/event table and root-motion policy. Output an editable rig, named clips with metadata, explicit GLB and source/runtime motion evidence.

Use [Blender](../studio-blender/SKILL.md) for nonhumanoid bones, shape keys or procedural/keyframed motion. A simple two-bone or deforming setup is sufficient for a bounded response when it preserves silhouette and readable contact. For humanoid services, verify provider-specific body/topology/texture eligibility first; never assume an alien body is supported.

Establish a neutral rest pose and deliberate pivot/root, name deform bones and weight groups, and check weight sums and parent dependencies. Test the maximum intended bend/twist, compressed/extended shapes and attachment points before animating. Save rest and stress evidence even if the rig is small.

Author at least the clips needed by the work card, each with name, duration, sample rate, loop flag and in-place/root-motion rule. Use named NLA tracks for the packaged collection exporter. Keep unrelated actions and competing live action/NLA evaluation out of the export. Check first/last frame equality for loops and intentional anticipation/settling for responses.

The original `blender fixture` creates a nonhumanoid harbor bell with `Root`/`Frond`, a two-second `idle` loop, one-second `response`, and ten rest/stress/motion images. This is a deformation pipeline test, not a finished creature performance. Its scripts are [fixture authoring](../../studio_tools/blender_scripts/fixture.py) and [hierarchy export](../../studio_tools/blender_scripts/export.py).

Reimport the GLB into a fresh Blender process and inspect skin, bones, clips, duration and dimensions. In Godot, explicitly set the loop policy and idle→response→idle transition/blend. Observe at least two loops and a response via ordinary input. Pose-change assertions are useful technical evidence but cannot establish appealing motion or contact.

Identify face/lip-sync, retargeting or root-motion integration as separate scoped requirements when needed; do not add a full talking-character system by default. Hand clip/event metadata to [Godot](../studio-godot/SKILL.md) and timed cues to [audio](../studio-audio/SKILL.md), then use [review](../studio-review/SKILL.md).

For an explicitly scoped UniMate experiment, the [optional reference worker](../../docs/unimate-experimental.md) uses the existing local request/receipt protocol and owned runner. It requires pinned local assets, explicit animated-reference conditioning and a supported source/conditioning rig profile; rest-only inference remains unvalidated. It bundles no model/environment and establishes no production or enforced-offline claim. Preserve the original rig, author/bake through the existing Blender route, review raw playback first, and retain comparison/human review before packaging or game adoption.

The optional source bake/verification scripts use project-owned wrappers through `studio blender run`. Recover the full conditioning rig, calibrate identity-delta rest into actual source bone bases, then project originals by name. Keep authored clips, geometry/skin/rest/materials and scene timing in the isolated editable copy; stage export-only30Hz copies without changing the source. Verify fresh GLB motion against source-space expectations and exact existing runtime skin buffers, disclosing pre-existing tiny-weight export loss separately. Register only independently reviewed derivatives as unselected candidates; keep visual, loop, controller and Godot qualification pending.

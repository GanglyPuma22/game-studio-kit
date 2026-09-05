---
name: studio-art-direction
description: Translate exact visual references into a versioned, buildable game-art contract and compare concept or runtime candidates for a coherent asset family.
---

# Studio art direction

Inputs: actual reference images/files with ID, version, rights and decision status; player scale/camera; target hardware; work card. If a selected image is missing, preserve its known ID and request/recover the image rather than reconstructing it from a style nickname. Output a versioned art contract, asset briefs, reference index and comparison verdict.

Inspect silhouette, proportion, palette/value grouping, material separation, edge treatment, light/shadow, density at ordinary viewing distance and motion language. Turn observations into buildable choices: metres, pivot, relative feature size, roughness/metallic behavior, contour strategy and what must remain readable in motion. Separate direct observations from proposed adaptations.

Use available host concept-generation tools only when they answer a specific unresolved question and session authorization covers them. Provided references and original procedural tests remain viable without image generation. Archive the exact prompt, input hashes, reported tool/model identity (unknown if not exposed), output hash and what uncertainty the result resolved. A concept is not an engine screenshot.

Before producing an asset family, test one close-up object and one normal-camera composition under target-engine lighting. Compare the approved reference and candidate in the same decision context. Name what drifted and which constraint needs correction; do not describe a successful render as “style matched” without visual examination.

Read the adapted [asset-production guidance](references/asset-production.md) when planning a family. Route source geometry/material work to [Blender](../studio-blender/SKILL.md), motion to [animation](../studio-animation/SKILL.md), and runtime recreation to [Godot](../studio-godot/SKILL.md). Read [acceptance](../../references/acceptance.md) before giving a verdict. Deliver exact reference IDs and instructions another artist can reproduce, including intentionally simplified features.

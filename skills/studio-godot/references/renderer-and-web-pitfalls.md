# Renderer and browser pitfalls

Found in one game (Godot 4.4.1, Oct and Nov 2026) that ships the same content on the desktop renderer (Forward+) and in the browser (Compatibility). Each item cost at least one review round. Dated, so re-check against the engine version in use.

Check every look, effect and sound on both renderers before a review. A pass on one says nothing about the other.

## Colour

- The Compatibility renderer shades in sRGB. A shader that reads vertex colour converts it under `#if CURRENT_RENDERER == RENDERER_COMPATIBILITY`, or the same model comes out a different colour in the browser.
- Store palette colours linear (`srgb_to_linear`) so they match a model's vertex colours.
- Pass `Vector3`, not `Color`, for a `vec3` uniform.

## Many small pieces

- Draw many small pieces (leaves, debris, buds) as one `MultiMesh` with one shader that reads a per-instance delay from the custom data. A frame then sets one uniform, not hundreds of transforms.
- On Compatibility, setting single instances after the first upload corrupts their colours and custom data. Write the whole `MultiMesh.buffer` instead.
- `CPUParticles3D` with billboard quads renders the same on both renderers.

## Effects against a bright scene

- Additive glow vanishes against a bright sky. Use alpha-blended shapes with a dark rim.

## Animation

- Give every `AnimationTree` `Transition` an initial `transition_request`.
- A `OneShot` needs a couple of nonzero steps before it shows. When the action lands on the tick it starts, step the tree on to the impact pose.
- A `BoneAttachment3D` lags its bone by a frame. Read attachment points from `skeleton.get_bone_global_pose`.
- Set procedural bones (scarves, tails) from their rest pose every frame, so they do not accumulate.

## Sound in the browser

- Play a world sound flat: work out its loudness from distance once, when it starts, and play it on a plain player. That avoided volume changes mid-sound and a looping hum.

## Scripts

- A `:=` on an untyped value does not parse, and one script that does not parse breaks every scene that loads it. Parse every script before a hand-over.

## Drawing both renderers on a cloud box

- Compatibility: an Xvfb display and `--rendering-driver opengl3`.
- Forward+: lavapipe (`mesa-vulkan-drivers`, `libvulkan1`, `VK_ICD_FILENAMES` pointing at `lvp_icd.json`) and `--rendering-method forward_plus`.
- Restart Xvfb when a render writes nothing.

For what such a box can and cannot show (frame rates, timings), see [studio-cloudrun](../../studio-cloudrun/SKILL.md).

# Runtime material handoff

The functional profile is Blender 5.0.1 → glTF 2.0 GLB → Godot 4.5.1 standard. [Godot interchange guidance](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/available_formats.html) favors explicit glTF; retaining `.blend` adds editability without making consumers import Blender sources.

| Source intent | Runtime check |
|---|---|
| Principled base color | Imported albedo color/texture and correct sRGB treatment |
| Roughness/metallic | Matching scalar or packed texture channels; light at play scale |
| Normal texture | Tangent basis, normal orientation, UVs and seams |
| Alpha | Opaque/cutout/blend chosen deliberately; inspect sorting and silhouette |
| Procedural nodes / stylized contour | Bake to textures or implement a reviewed Godot shader; never imply automatic equivalence |
| Emission | Runtime exposure/glow and target-renderer support |

Two engine behaviours that only an engine render shows:

- In Godot 4, `StandardMaterial3D`'s detail normal replaces the base normal where the detail mask is on; it does not layer on top. Adding micro-grain that way silently erases a baked relief. Use a custom shader with a whiteout (or similar) normal blend, or keep the detail mask well under 1.
- A shader that writes `DEPTH` is depth-tested against the value it writes. Godot 4 uses reverse-Z (the far plane is 0.0), and whether a far-plane write draws depends on the renderer's depth clear and compare, which differ between renderers. A boolean cut that looks right in Blender can vanish, or show through, in the engine; check it in an engine still on the game's own renderer.

For anything that depends on a custom shader, transparency, depth or fog, engine stills are the authoritative review evidence; lab renders can pass what the engine draws wrong. Give asset reviews the game's own environment pieces where they matter (water plane, sky, anti-aliasing mode), because some defects only appear against them.

Keep runtime materials project-owned so reimport does not erase intentional overrides. Test mip/distance behavior, texture memory and material slots on the target renderer. Reimport clips separately from their playback rules: [AnimationTree](https://docs.godotengine.org/en/stable/tutorials/animation/animation_tree.html). Review the actual mix using named [audio buses](https://docs.godotengine.org/en/stable/tutorials/audio/audio_buses.html).

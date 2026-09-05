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

Keep runtime materials project-owned so reimport does not erase intentional overrides. Test mip/distance behavior, texture memory and material slots on the target renderer. Reimport clips separately from their playback rules: [AnimationTree](https://docs.godotengine.org/en/stable/tutorials/animation/animation_tree.html). Review the actual mix using named [audio buses](https://docs.godotengine.org/en/stable/tutorials/audio/audio_buses.html).

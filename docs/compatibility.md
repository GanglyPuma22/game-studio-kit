# Compatibility and verification

Implementation validation date: September 5, 2026. This matrix distinguishes executed helper/app behavior from native host and provider claims.

| Configuration / capability | Result | Evidence / limit |
|---|---|---|
| Python 3.11+ stdlib helper interface | Implemented; local test run recorded below | No pip runtime dependencies |
| Blender 5.0.1 Windows, owned background through explicit WSL mapping | Passed real fixture generation, ten PNG renders, GLB export and fresh-process import | Four meshes, three materials, one skin/two bones, idle 2 s / response 1 s; Blender display-only custom shapes excluded from bounds |
| Godot 4.5.1 standard Linux x86_64 | Passed real headless import and runtime smoke | Imported clips/rig, moved 2.458 m, one response, audio player start, pose change, return to idle |
| Audio during headless Godot smoke | Dummy driver; listening not_run | Playback API invocation is not audible mix evidence |
| Native Windows Python and Godot operation | Unverified | Exact setup/smoke supplied; Windows Blender background does not establish this full host route |
| Actual registered Windows ChatGPT/Codex coordinator, separate project cwd | Unverified | Must invoke installed coordinator, resolve sibling/shared resources and run a real route in a new conversation |
| Native computer use, ordinary controls, runtime visual/motion/listening review | Not run | Host tool/app permissions and audible capture route required |
| GPU renderer / frame performance | Unverified | Eevee source images and fixed headless physics step are not a target-hardware performance benchmark |
| Meshy image/preview/refine/remesh/retexture/rig/animate | Implemented narrow profiles; mocked contract tests | No paid calls, entitlement/rates/output-quality validation |
| ElevenLabs effects/speech/music | Implemented bounded profiles; mocked contract tests | No live voice/music/effects generation or rights certification |
| Gaea installed-version build recipe | Implemented and mocked | No entitled/native installation or UI graph build executed |
| Blender MCP 1.9.1 pinned addon/server recipe | Documented, telemetry-off configuration supplied | No addon installed, connection started or interactive pairing tested |
| macOS / other engines | Extension targets | Not tested |

The original functional example is ready for technical reproduction and consolidated review. Target-native smoke and the production art pilot remain required before calling the package ready for that pilot configuration or ready for public release. No target-host/perceptual acceptance has been inferred from the helper test suite.

See [testing](testing.md), [native smoke](windows-smoke.md) and [source provenance](../upstream-lock.json). Executed test counts and the final package review are recorded in [implementation validation](validation.md).

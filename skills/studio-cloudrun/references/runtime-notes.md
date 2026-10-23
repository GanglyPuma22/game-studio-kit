# Runtime notes

What is known about the places a cloud run draws, from Salvage's Colab runs (Oct 2026, a 29 GB Godot 4.7 game) and Skybreak's clip recorder (Oct 2026, a small Godot 4.4.1 game). Dated, so re-check anything that matters.

## Cloud agent box (`where: here`)

- No GPU. `apt install mesa-vulkan-drivers xvfb ffmpeg` gives lavapipe; Godot's Forward+ renders correctly under `xvfb-run` and reports `llvmpipe` as the device.
- Skybreak at 1280x720, 4 cores: about 2 frames drawn a second. A 7-second clip at 30 fps took 80-90 s including start-up and fast-forwarding to the moment.
- Record with the engine's own fixed-step movie writer (Godot `--write-movie <file>.avi --fixed-fps 30`): game time advances one step per frame however slow the drawing is, so clips play at normal speed and sound is mixed in step (the AVI carries it).
- Skipping drawing while waiting for a moment: in Godot 4.4 on lavapipe, `RenderingServer.render_loop_enabled = false` alone still waited on the GPU every frame (about 270 ms a frame). Also setting `get_tree().root.disable_3d = true` brought it to about 25 ms. Turn both back on a few frames before the clip starts so it opens on a fresh picture.
- Anything driven by wall-clock time (`Time.get_ticks_msec()`) runs at the wrong speed in a fixed-step recording: pulsing glows, timers, cooldown displays that read real time. Note it next to clips that show such effects.

## Colab GPU runtime (`where: colab`)

- Paid accounts with compute units may run remote shells; `colab new --gpu L4`, `colab ssh`, `colab stop` from the colab CLI on the service host. The account held 2 L4s at once; a third request was refused, so jobs wait for a free one.
- L4 costs about 1.5-1.8 compute units an hour. Start-up and copying a small game in take a few minutes.
- Screen: Xvfb `:99` with Mesa GLX, started with `-noreset` and an empty environment, then Vulkan through the host's NVIDIA ICD (`/usr/lib64-nvidia/libGLX_nvidia.so.0`). `xvfb-run` alone gave no display; the NVIDIA X server failed without a real display device.
- Presenting to that screen fails ("Couldn't get Vulkan surface present modes", VkResult -13) on every frame with stock Godot. Frames still render correctly (stills, movie writer), but each frame stalls, GPU timers read 0 and frame times drift. Salvage built a skip-present engine for GPU timing; clips and stills do not need it.
- The VM's CPU is a slow server part: never trust CPU or physics timings from it.
- Colab's own Drive mount needs a browser click on every new runtime; don't depend on it unattended. Copy files in over ssh instead.
- Connection drops happen (websocket, ssh, HTTP 429 right after start-up); retry the first ssh a few times, and rerun a job once when its log shows an infrastructure error.

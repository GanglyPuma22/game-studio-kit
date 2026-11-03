# Prompt anatomy (reference-video jobs)

Build each prompt from fixed blocks in this order, so one change reaches every chunk.

1. **Layout** — what Video 1 is and what to copy. "Video 1 is a rough layout. Copy its camera moves, its cuts and their timing exactly. Plain coloured PILLARS only mark where each character is (white = A, teal = B, ...): perform those bodies yourself from the brief, with real weight and fluid motion. Grey CLAY figures are posed: follow their poses and placement closely. Ignore the layout's grey colours, flat tints and blocky shapes; they only say who is where."
2. **Images** — the role of each attached image, numbered. "Image 1 is the target look (light, lens, texture, grade); take only its look. Images 2 and 3 show A (concept art, game model)." Then: "Keep each character clearly recognizable from those images, but render everything in the target look, not in the references' drawing or game style."
3. **Cast** — one fixed sentence per character in the shot, identical in every prompt.
4. **Scale** — true sizes in words, every time.
5. **Beats** — `start-end s (grade): brief`, one per shot in the chunk. A brief names the action, the energy, the camera's relation and what the shot must never show.
6. **Rules** — "Never a pause, freeze, reset, slow-down or stop unless the brief says so. No camera shake except on the named impacts. Add no cuts beyond the layout's."
7. **Look** — the picked look's paragraph, then a short avoid-list (weightless motion, sinking feet, extra limbs, text, logos, UI).

Keep a dry-run mode that prints every prompt with its character count and estimate; read the prompts before asking for a go. Some models cap prompt length (Aleph 2: 1000 characters).

Director's brief example (pillars): "Side by side at a full sprint, low and fast, arms and blades moving; the camera tracks side-on at their speed. Never a slow-down."

Tethered action (grapple lines, swings): "arcs, not zips; the line's tension shows in the body; legs trail, then snap in; the camera lags, then catches up; one clear pose before each hit." Don't ask for smears, animating on twos or frame stutters.

Keep `audio: false` on every clip; sound is built in the edit.

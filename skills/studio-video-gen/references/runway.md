# Runway API profile (checked 2026-11-02)

Base `https://api.dev.runwayml.com/v1`, header `X-Runway-Version: 2024-11-06`, `Authorization: Bearer <key>`. The developer API is a separate account from the Runway web app; credits are $0.01 each and bought in the developer portal. `GET /organization` returns `creditBalance`. `GET /tasks/{id}` returns `status` (`PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`) and `output` (signed, temporary URLs: download at once).

Pricing page: https://docs.dev.runwayml.com/guides/pricing/ . Re-check before each approval ask; the runner's table is a convenience, not a quote.

| Model (`model`) | Endpoint | Key fields | Credits (as measured) | Notes |
|---|---|---|---|---|
| `seedance2_5` | `video_to_video` | `promptVideo`, `mode: "reference"`, `references: [{uri}]`, `ratio`, `duration`, `audio`, `seed`, `promptText` | max(80, 30/s output + 15/s reference video) | Best of the three for restyle and for camera-only pillars. 4 s minimum per job, so short shots render in chunks. Also text-to-video with image references and no video. |
| `kling_4` | `video_to_video` / `image_to_video` | `videoUri`, `ratio: "auto_720p"`, `references` | 9.4/s x 2 (a 20% promotion ran to 2026-11-30) | Fluid motion from a first frame; good second choice. |
| `aleph2` | `video_to_video` | `videoUri`, `keyframes: [{uri, seconds}]`, `promptText` <= 1000 chars | max(56, 28/s) | Kept clay mannequins in our tests; avoid for restyle. |
| `gen4_image` | `text_to_image` | reference images | about 8 per image | Look stills. |

Practical notes:
- Seedance rejects reference images wider than about 2.5:1; crop look stills before submitting.
- Inline media as data URIs works up to about 5 MB per file; nothing has to be hosted.
- Jobs run in parallel; submit all, then poll every 15 s. A 6 s Seedance job took a few minutes.
- A rejected request costs nothing; an accepted one is charged whatever you think of the result.
- Credits already accepted in this run may not show in the balance yet, so the runner reserves them.

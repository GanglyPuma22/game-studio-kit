# OpenRouter profile (checked 2026-11-02)

Base `https://openrouter.ai/api/v1`, `Authorization: Bearer <key>`. One key reaches many image and video models, which makes it the cheap way to compare models and the fallback when Runway lacks one.

- **Video:** `POST /videos` with `model` (e.g. `alibaba/wan-3.0`), `prompt`, `resolution`, `aspect_ratio`, `duration`, `generate_audio`, `seed`, optional `frame_images: [{type: "image_url", image_url: {url}, frame_type: "first_frame"|"last_frame"}]` and `input_references: [{type: "video_url", video_url: {url}}]`. Poll `GET /videos/{id}` until `status` is `completed`, `failed`, `cancelled` or `expired`; download `GET /videos/{id}/content?index=0` with the key. The final poll carries `usage.cost` in dollars.
- **Video references must be HTTPS URLs**, not data URIs. A temporary tunnel (e.g. a Cloudflare quick tunnel over a local folder) works; close it after the run.
- **Images:** `POST /chat/completions` with `modalities: ["image", "text"]` and image inputs as `image_url` parts; the image comes back as a data URL in `choices[0].message.images`. Use it for look rounds (about $0.04-0.06 per image with several inputs; budget $0.08).
- **Price:** Wan 3.0 was about $0.10/s at 720p list, about double with a video reference. Give each job an `est_usd`.
- `GET /credits` returns `total_credits` and `total_usage`; the runner prints the difference.

Our measured quality: Wan 3.0 from a first frame alone was weak, and with a video reference it copied the blockout's game look. Use it for cheap comparisons, not as the film model, unless a newer model changes that.

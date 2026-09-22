# Optional provider setup

The local functional fixture makes no paid requests. No helper import, doctor or setup command probes the network or downloads a model. Provider credentials are read from the configured environment variable names, and — only when the host config declares them — from the `KEY=VALUE` files listed in its optional top-level `credential_files`. Nothing is searched for implicitly: no shell profile, no home directory, no `.env` beside the project, and a relative entry follows the host config file's own directory rather than wherever the command was run from. A value read from a declared file is handed to that one provider request and is never exported into the environment or inherited by a child process. Never put a key in a project, task JSON or command argument.

For Meshy, configure `MESHY_API_KEY`; for ElevenLabs, `ELEVENLABS_API_KEY`. The Python helper uses stdlib HTTPS and sends one request for each explicit submit/generate action. `meshy balance` and `audio balance` are the two read-only calls: `meshy balance` reports the remaining account balance and `audio balance --provider elevenlabs` reports the account tier, status and character counts. Both write no record and both are the check to make before asking for approval to spend; `audio balance --provider fish` answers `unsupported`, because this adapter knows no Fish account endpoint and will not guess one. `doctor` reports environment-variable presence only, so a host that keeps its key in a `credential_files` entry is reported as `needs_setup` there while the provider commands work. Authentication, model access, credit balance, rate limits and service/output rights require your current account check. The [supported Meshy profiles](../skills/studio-meshy/references/api.md) and [audio entrypoint](../skills/studio-audio/SKILL.md) contain the production route.

A budget record for an already authorized run has this shape (replace the example numbers/units with actual checked account facts):

```json
{
  "authorized": true,
  "work_card": "work-001",
  "rate_checked_at": "2026-09-05",
  "units": "account credits",
  "estimated": 1,
  "maximum": 1
}
```

The numbers above are **not provider prices**. Each new paid request, including refine/retexture, consumes its own allowance and must stay inside the work card's remaining aggregate budget. The helper prevents blind resubmission of an existing intent; it does not maintain an account ledger or enforce service-side billing limits. The coordinator tracks total spend and stops at the card's cap.

A rights/provenance input for audio needs a `rights` field explaining source/voice permission and intended usage. Record provider/model/voice IDs without conflating the fictional character with the backend. Third-party repository licenses do not grant service access or rights to arbitrary uploaded content.

Task outputs/response JSON can include private prompts, account metadata and expiring signed URLs. Keep them in game-owned ignored artifact/source directories and audit before sharing. Archive successful outputs promptly. Unknown POST outcomes are reconciled in provider history before deciding whether a genuinely new request is warranted; never automatically retry them.

Gaea needs an installed, entitled, UI-verified graph/command recipe; [Gaea route](../skills/studio-terrain/references/gaea.md). Optional Blender MCP needs a matched pinned addon/server and explicit telemetry-off configuration; [MCP route](../skills/studio-blender/references/mcp.md). Neither is installed by setup.

For encoded audio, detect FFmpeg/FFprobe using doctor. An explicitly scoped conversion is `ffmpeg -i <original.mp3> -c:a pcm_s16le <runtime.wav>`; keep the original. Use a distinct output, intentional sample/channel settings and compare listening quality. FFprobe's stream duration/rate/channel metadata is evidence of format, not artistic quality. A local TTS model is optional future scope, not a hidden setup dependency.

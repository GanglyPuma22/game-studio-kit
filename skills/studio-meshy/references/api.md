# Meshy supported profiles

Schema review: September 5, 2026. This is a deliberately narrow local contract, not a universal API passthrough. Live provider testing is pending. API base is `https://api.meshy.ai`; the configured key is sent only in an Authorization header. Generation defaults to explicit `meshy-6`; `meshy-5`/`meshy-7` are accepted explicit choices. Do not substitute `latest` silently.

| Profile | Endpoint | Required local request fields |
|---|---|---|
| image | `/openapi/v1/image-to-3d` | `image_url` (HTTPS PNG/JPEG or image data URI) |
| preview | `/openapi/v2/text-to-3d` | `prompt`; helper fixes `mode: preview` |
| refine | `/openapi/v2/text-to-3d` | `preview_task_id`; helper fixes `mode: refine` |
| remesh | `/openapi/v1/remesh` | `input_task_id` |
| retexture | `/openapi/v1/retexture` | `input_task_id`, `text_style_prompt` |
| rig | `/openapi/v1/rigging` | `input_task_id`, `height_meters`, separate checked eligibility |
| animate | `/openapi/v1/animations` | `rig_task_id`, integer `action_id` from current library |

GLB is the supported requested runtime format. See [profile validation](../../../studio_tools/adapters/meshy.py) for optional fields. Rig eligibility records humanoid_biped, textured, checked, clearly separated limbs and measured face count at or below 300,000. A generated success must be inspected before it becomes rig input. Source texturing/topology failures remain asset work.

```text
python <KIT>/scripts/studio.py meshy submit --project <GAME> --profile image --request requests/image.json --budget requests/budget.json --record artifacts/tasks/image-001.json --config <HOST>
python <KIT>/scripts/studio.py meshy observe --project <GAME> --record artifacts/tasks/image-001.json --attempts 12 --interval 5 --config <HOST>
python <KIT>/scripts/studio.py meshy archive --project <GAME> --record artifacts/tasks/image-001.json --output source/image-001
```

Do not automatically repeat submit. `SUBMITTING`/`SUBMISSION_UNKNOWN` without ID must be reconciled against the account's task list/history using request identity; use `meshy reconcile --task-id <verified-id>` to attach that ID. Observation resumes GET on the existing endpoint and preserves failed/expired/unavailable records. Archive uses temporary files, content-length/signature checks, file hashes and per-file progress. A retry of archive or GET is distinct from a new paid request.

The task record retains submitted options, request digest, endpoint/model, budget, eligibility, provider task ID/status/full response and returned credit/expiry fields, plus local output names/hashes. Signed asset URLs and private prompts belong in project-owned artifacts. Budget numbers are a per-run input; no historical credit price is guaranteed here.

Primary sources: [Image](https://docs.meshy.ai/en/api/image-to-3d), [text preview/refine](https://docs.meshy.ai/en/api/text-to-3d), [remesh](https://docs.meshy.ai/en/api/remesh), [retexture](https://docs.meshy.ai/en/api/retexture), [rigging](https://docs.meshy.ai/en/api/rigging), [animation](https://docs.meshy.ai/en/api/animation), [retention](https://docs.meshy.ai/en/api/asset-retention). Recheck schemas before extending a profile; add a meaningful contract test and update provenance.

# One bounded Tripo operation

This is a host-neutral procedure, not a saved request schema. The kit has no
Tripo helper/backend. Check the currently installed official client or Studio
surface before using it; a feature in Studio or one SDK/API version does not
prove that another version supports it.

## Verify capability and spend

Use [official API documentation](https://developers.tripo3d.ai/en/docs/introduction)
and [SDK integration](https://developers.tripo3d.ai/en/docs/sdk) to select a
supported route. Record the exact client version/revision, API version/region,
model identifier, operation, format and documented parameters. Verify input
limits, allowed model transitions and any dependencies such as import. Do not
copy old segmentation/completion/remesh flags into a different model contract.
For a CLI, verify its official source and installed help; its presence alone
does not establish the requested operation. For Studio, use the actual account,
operation and export dialog as evidence.

Read the selected surface's current balance before asking for spend approval.
The [API account documentation](https://developers.tripo3d.ai/en/docs/account)
describes available/frozen wallet balances. Tripo's
[billing distinction](https://www.tripo3d.ai/help/api-plugins/tripo-studiotripo-api)
states that API credits and Studio subscription credits are separate. Never
infer an API allowance from a Studio subscription or transfer a quote between
these pools. Check current pricing/quote and entitlement for the exact model,
options and export, including prerequisite operations. Record its timestamp,
currency/credit units, maximum authorized spend and remaining allowance. No
automatic top-up, upgrade or surface switch is authorized by this skill.

Before upload/submission, record a compact matrix for the selected account/plan:
model and export-format eligibility; remaining export allowance; output-use
license/commercial entitlement; input/output public or private visibility. Verify
these against the current plan and rights information, not a frozen free-plan
limit. A public, non-commercial comparison candidate stays outside production
assets. An unavailable export or incompatible required privacy/use right must
change the route before spending, rather than become a surprise at download.

The work card must state numerical maximum submissions, total credits/cost,
wall time and desired triangle/material/texture/dimension limits. One target
operation is the default; list and price required prerequisite tasks explicitly.
If a target cannot run within those bounds, return the specific incompatibility
and continue useful local work. Do not add speculative variants or repairs.

## Execute and retain ownership

Create a unique receipt before the request. A private task record may hold data
needed to resume. Its shareable projection contains only: receipt identity,
owner, operation/model/client/API identity, checked documentation and dates,
reference/source paths and hashes, sanitized request options, numerical budget,
balance/quote evidence, submission time, task ID and parent task IDs, terminal
status, reported charge/refund, local outputs/hashes, verification and review
status, and the verified plan/export/license/visibility matrix. Never include API keys, auth headers, STS credentials or signed URLs in
the shareable projection; do not blindly publish raw provider JSON.

Read credentials through the host's approved private mechanism. Do not pass
keys in command arguments, print their contents, commit them or assume the
kit's Meshy credential loader is a Tripo integration.

Submit the authorized target once. Persist returned IDs before waiting. The
[official Python SDK reference](https://github.com/VAST-AI-Research/tripo-python-sdk/blob/master/docs/API.md)
documents a task wait with a timeout; verify that method and its compatibility
in the installed version at use time. Set a finite timeout and invoke a
supported blocking client wait once. A client's own internal status handling
does not authorize an agent polling loop. A verified official blocking CLI is
also suitable when its timeout/output contract covers the selected operation.
In Studio, rely on its completion event/notification; do not repeatedly refresh
or query progress. If the host returns before the bounded process completes,
use exactly one supported completion retrieval sized to the remaining bound.

Preserve a task after an ambiguous transport failure or timeout. Reconcile it
with the same account using one supported retrieval before considering another
submission. Record unresolved status if reconciliation cannot establish its
outcome. Insufficient credits, terminal failure or unverified compatibility
does not authorize a retry, repair chain or new purchase.

## Archive, inspect and return

Download completed outputs promptly using the supported client or UI export.
Use a task-owned fresh directory, reject HTML/error payloads masquerading as
models, verify format signatures and parseability, then hash the local files.
A `.glb` filename alone proves nothing: check its glTF binary header/version,
declared length and importer result. Confirm other model/texture formats with
their actual format parser or decoder. Keep untouched originals and required
texture dependencies; perform cleanup/export in new project-owned files.
Expired URLs require supported retrieval for the existing task, not regeneration.

The foreground owner reviews in native Blender: compare silhouette, proportion,
identity and materials against the exact reference and original; measure total
triangles per specimen, topology/nonmanifold or disconnected regions, scale,
UVs, material/texture count and useful separation where relevant. Segmentation
names/counts do not prove usable boundaries, and fewer faces do not prove good
deformation or collision. Record missing/failed checks explicitly. Replication
and integration follow the declared review decision, then ordinary player-scale
runtime review when required. Human playtest acceptance remains separate.

Return the sanitized receipt and output pointers with measured bounds, actual
cost when reported, unresolved charges/tasks and the next concrete review
decision. Neither a downloaded model nor a clean import establishes visual,
interaction, animation or performance acceptance.

# Storage lifecycle

Read before allocating a checkout, full candidate/asset copy, build cache or
large evidence payload, and at closeout. This is production guidance, not an
automatic migration or deletion mechanism. Existing session authorization and
project-specific safeguards apply; record decisions in the
[work card](../templates/work-card.md) and [Return](../templates/return.md).

## Allocate deliberately

- Inspect existing checkout ownership, branch/HEAD and source overlay, active
  launch/service dependencies and free disk space before a large allocation.
  Reuse a suitable active checkout by default with its owner. Disjoint worker
  edits share that candidate with explicit file ownership; workers return small
  patches and findings rather than full game copies.
- An additional checkout needs a concrete isolation reason, owner, pinned source
  identity, estimated extra source/asset/LFS/cache/evidence bytes and retirement
  condition in the work card. Isolation is a choice for conflicting writes or a
  declared comparison, not an automatic allocation for every worker or run.
- Identify the canonical repository/branch, active candidate and playable
  fallback separately, including their shared dependencies. A filesystem-only
  candidate and uncommitted overlay are unpublished state; a path or hash does
  not version their contents. Preserve a compact initial source baseline before
  new edits so a later checkpoint can exclude unrelated work.
- Do not copy whole `.godot`, compiler targets, evidence trees, package history
  or asset stores into another candidate by default. Reference sealed packages
  by exact manifest/content identity and keep required runtime paths explicit.
  Where a self-contained package needs materialization, declare the selected
  inputs and allocation. Never alter active launcher paths mid-run.

## Separate source, evidence and caches

Version deliberate code, editable art, source textures/audio and required assets
through authorized Git/Git LFS checkpoints. Stage named reviewed paths and keep
credentials/private configuration out of published archives. A storage plan does
not authorize commits, pushes, merges, installs or an asset-rights decision;
overnight `snapshot_commit` rules still govern that run's checkpoint.

Keep rebuildable import/compiler caches separate from source and unique evidence.
Reuse compatible compiler caches under an explicit toolchain/target/flags/profile
namespace; shared Git/LFS object stores and package roots have their own owner
and dependency record. A shared cache is mutable: before a later build overwrites
it, pin a selected executable/package and hash at a stable run path. Coordinate
concurrent builds and never clean a cache used by a build, service or fallback.
An import with missing originals is a preservation gap, not disposable data.

## Bound evidence at capture

Declare summary fields, sampling frequency, duration, record count/byte bounds
and essential raw retention before a diagnostic run. Default to compact metrics,
content/input identities and referenced manifests; do not serialize full scene
state each tick. Large full-scene dumps are opt-in for a named uncertainty, with
bounded sampling and size and an explicit retention purpose. At the bound, record
truncation or stop optional capture; never silently discard required evidence
or claim an incomplete payload proves the intended result.

Preserve essential raw inputs, exact recipes/configuration, process/launch
receipts, failures and selected player/review captures losslessly. A summary
cannot replace the raw material needed to reproduce or explain a failure.
For completed cold evidence, lossless compression/compaction may reduce storage
only at an owner-controlled checkpoint: inventory original paths/hashes,
verify decompressed bytes and restore steps, and record archive identity plus
any replacement path mapping. Keep active files and referenced receipt paths
intact. Removing originals is a separate retirement decision; do not blanket
ignore generated output before unique inputs and tracked contents are classified.

## Closeout

The Return lists canonical source and current candidate/fallback, unpublished
overlays, unique assets/evidence/saves/authoring stores/drafts, live dependencies,
cache/shared-object roots, measured growth and recovery gaps. State which source
checkpoints and evidence archives exist and what their restore checks established.

A remote branch pointer or reachable commit is not a full backup. Before releasing
local state, verify exact remote refs and required LFS objects, plus preservation
of uncommitted, untracked and ignored unique state and nested repositories.
For an off-machine archive, verify entries/hashes and restoration and confirm
remote recovery; a local copy in a sync folder alone is insufficient.

Propose an exact keep/archive/remove-candidate/hold list with owner release,
dependencies and preservation proof. Age, silence, a merged PR, an ignored path
or commit reachability alone grants no removal authority. Respect the user's
exact-list cleanup approval and revalidate paths, ownership and recovery at
execution. No blanket or unattended automatic deletion is enabled here.

# Approved concept first, then a free base if one fits

A game opts in by listing cases in `art_pipeline.concept_required_for` (the [project template](../../../templates/project.json) lists new models and look-changing remodels). For an opted-in case, two steps come before any modelling: an owner-approved concept image, and a short check for an openly licensed base mesh or texture. Both exist because modelling is the expensive step. A model built against a style nickname or a builder's private idea gets judged against a target nobody agreed on, and critic rounds then measure drift from nothing. A base that already carries the right silhouette saves hours that a from-scratch build spends getting there.

The project record's `art_pipeline` block holds the per-game values these steps need: who approves, which image route is allowed, which licences are acceptable and the budgets a base must be reshaped to ([project template](../../../templates/project.json)). A game that leaves a value unset has not decided it; ask for the decision rather than assuming one.

## 1. Concept brief

Write a short brief beside the asset's work before generating anything: role in play, habitat or setting, scale and the closest player view, what it must not look like (the obvious real-world or genre look it should avoid), and three or four distinct directions. Name the reference IDs it builds on. A game that grounds its content in real-world analogues (ecology, architecture, machinery) states the analogue and what is borrowed from it, so the design has a reason a later reviewer can check.

## 2. Generate options

Generate a small, even set: about two images per direction. Use the route the game declares in `art_pipeline.concept_route`; paid image providers run only under a recorded authorization, the same budget record paid mesh providers use ([production contracts](../../../references/production-contracts.md)). Archive each image with the tool, the reported model (unknown if not exposed), the exact prompt, input hashes and output hash. Concept images are inputs, never runtime art and never engine screenshots.

## 3. Owner picks

Show the options together, on one page, and get one picked or a stated mix with notes. The approver is `art_pipeline.concept_approver`; a builder never approves its own concept. In an authorized unattended run, a builder may mark a provisional pick and continue on it, but the asset cannot leave `working` on a provisional concept.

## 4. Record the approval

Keep the approved image as a project reference with its ID, version, hash, approver, date and the owner's notes, and add it to the asset record's `provenance.concept`:

```json
"concept": {"reference_id": "concept-shrub-03", "approved_by": "owner", "approved_at": "2026-01-01", "file": {"path": "references/concepts/shrub-03.png", "sha256": "<hex>"}}
```

`validate-record` checks the file hash and that `approved_by` names someone. It cannot check that the person approved it.

## 5. Look for a free base

Before modelling from scratch, spend a short, bounded look on openly licensed sources such as Poly Haven, ambientCG, Quaternius, Kenney, or Sketchfab filtered to CC0 and CC-BY. Decide case by case for this one asset; do not bulk-download or build a library. Some hosts (cloud containers behind a proxy) cannot reach these sites; fetch from a host that can, into the project's reference folder with hashes, and say which host fetched it.

- Prefer CC0. Use CC-BY only with the attribution recorded exactly as the licence requires, and carried into the game's credits.
- Skip anything NonCommercial, NoDerivatives, editorial-only, "free for personal use", scraped or with an unclear licence. When the licence page and the download disagree, skip it.
- Keep the downloaded original untouched beside its hash; reshaping happens in a new source file.
- Record the base in `provenance.base`:

```json
"base": {"source_url": "https://example.org/asset/123", "licence": "CC-BY-4.0", "author": "Name", "attribution": "Asset Name by Name, CC BY 4.0", "retrieved_at": "2026-01-01", "file": {"path": "source/bases/asset-123.glb", "sha256": "<hex>"}}
```

`validate-record` refuses NC, ND or unknown licences in `provenance.base` and a CC-BY licence without attribution. Keep the game's `art_pipeline.base_licences_allowed` stricter if it needs to be.

A found base is a starting mesh, not a drop-in. It is reshaped to the approved concept, cut to the game's triangle budget for its class, given the game's LOD chain and qualified with `blender inspect` like any provider mesh ([Blender](../../studio-blender/SKILL.md)). When nothing fits within the bounded look, say so in the work card and model from scratch.

## 6. The concept is the target

Put the approved image into every critic brief and every side-by-side comparison for that asset. Once an asset has an approved concept, fit to it (silhouette, proportions, palette) is the craft check; see the [critic loop](../../studio-review/references/critic-loop.md). A paid generator ([Meshy](../../studio-meshy/SKILL.md), [Tripo](../../studio-tripo/SKILL.md)) takes the approved concept as its reference and runs only after the free-base check found nothing usable.

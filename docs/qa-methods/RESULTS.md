# QA methods experiment

## Session 2026-10-21 — proposal, no experiment run

User-visible result: no Fieldbook judgements collected; no method scores available.
The user is present and must agree each major step before execution. The next
decision is the 12-model sample and a one-model Fieldbook labelling pilot.

Authority: salvage origin/claude/project-thread-azi77u at
17b37d6582bbcc0bfcc2db157e4205a95819c404, docs/codex-plan/lanes/J-qa-methods.md
and docs/codex-plan/RULES.md. Source inventory: salvage-project-context,
codex/register-qa, codex-out/register-qa/MANIFEST.json, Git blob
c8895accbbc36d4ee7e640643572a906ee426e3a.

## Proposed answer-key protocol — awaiting agreement

1. Pin each exact Fieldbook attempt, upload SHA-256, LOD, view, lighting/style,
   camera settings and animation state. A model ID alone is not an attempt.
2. Inspect together in the Fieldbook: rotate, examine close-ups, inspect LODs
   and available animation. Record one observable issue per row, its location,
   evidence frame, severity, and the user's decision. Preserve explicit
   'nothing wrong in inspected views' and 'uncertain/not inspected' labels.
3. Use agreed severity anchors: major impairs recognition/use or is conspicuous
   at intended viewing distance; minor is visible but does not impair use.
   User judgement settles aesthetic disputes. Freeze a versioned answer key
   before scoring; later additions require separately recorded adjudication.
4. Treat absent metadata, unsupported inputs and timeouts as coverage or
   execution limitations, not proven visual defects. Do not invent accepted
   LOD switch distances. Static images cannot establish motion quality.
5. Compare issue-level hits, misses, false alarms and unassessable cases;
   de-duplicate repeated claims against the same defect. Record elapsed time,
   human preparation/review time, and available usage separately. Do not infer
   zero cost when usage is unavailable. No scores until labels and reviews exist.

## Proposed stratified sample

Selection covers three creatures, three trees, two ground-cover models,
one composite prop and three rock forms. This is a small purposive sample,
not a prevalence estimate or a claim about all 26 families. No model is
pre-labelled clean or defective.

| # | Fieldbook model ID | Coverage reason | Answer key |
|---|---|---|---|
| 1 | bellows-slug | Soft creature and morph/LOD behaviour | Pending |
| 2 | chalk-mite | Articulated creature and material detail | Pending |
| 3 | night-midges | Small creature and fine silhouette | Pending |
| 4 | shelf-tree | Broad layered tree form | Pending |
| 5 | highland-treeline-spire-c | Candle tree form | Pending |
| 6 | highland-treeline-spire-d | Windward tree form | Pending |
| 7 | mossy-log | Composite woodland prop | Pending |
| 8 | upland-litter | Ground-cover assembly | Pending |
| 9 | coast-fine-tussock | Thin foliage | Pending |
| 10 | fallen-block-h2 | Bedded rock form | Pending |
| 11 | lichen-boulder-h5 | Rock surface/material detail | Pending |
| 12 | columnar-outcrop | Repeated column geometry | Pending |

## Methods and blinding

Method A: preserve lane E baseline as-is. Any corrected-tool rerun is a separate
condition and requires agreement; no tool edits are approved yet.

Method B: fixed eight-view renders, close-up, LOD comparisons at authoritative
switch distances where available, and wireframe/x-ray; findings must cite
specific image IDs. Capture configuration and asset identity must be held fixed.

Blinding limitation: the inventory request returned the full MANIFEST, which
also exposed model_qa outcomes to this chat. This chat cannot honestly be called
blind to Method A. Joint answer-key construction would also expose this chat
to the labels. A genuinely blinded arm requires a fresh reviewer/context given
only images and neutral instructions, with no inherited history, QA results or
answer key. This is proposed, not yet dispatched or approved. The main session
retains visual review and user sign-off; a worker's claims are never acceptance.

Method C proposal: structured checklist versus free review, using the same
images in isolated contexts. Agree this variation and its budget with the user
after the pilot; no variants run yet.

| Method | Hits | Misses | False alarms | Coverage | Time/usage |
|---|---|---|---|---|---|
| A: lane E model_qa | Not scored | Not scored | Not scored | Pending audit | Pending |
| B: visual review | Not run | Not run | Not run | Pending captures | Not incurred/measured |
| C: agreed variation | Not selected | Not selected | Not selected | Not applicable | Not incurred/measured |

## Ownership and preservation

Notes owner: QA methods lane on laptop. Repository: GanglyPuma22/game-studio-kit,
branch codex/qa-methods; base origin/main at 97b3397d550e0043966ff9190e5cb1dd2062b412.
Dedicated worktree: C:/Users/maxim/Documents/salvage-wt/qa-methods-20261021.
Reason: lane brief requires isolation from installed kit and other task writers.
Allocation: one small source worktree, two Markdown notes; no game/asset/cache copy.
Retirement: only after user-approved exact deletion list and verified remote backup.
No render, Fieldbook launch, model_qa execution, geometry edit, paid API, permission
change, PR or merge performed. Installed kit is 0.1.14; fetched main's tip also
describes 0.1.14, despite the brief mentioning 0.1.15. Verify implementation and
version before any later rerun.

## Next agreement

Approve or revise the proposed 12 models, then inspect bellows-slug together as
a one-model answer-key pilot. Do not start batch rendering or QA runs yet.

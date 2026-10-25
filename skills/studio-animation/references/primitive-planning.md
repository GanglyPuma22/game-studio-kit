# Primitive-planned animation (experimental, opt-in)

Use only when the user chooses boxes-first / bounding-box / primitive-planned animation for the current task. Record `animation_workflow: primitive-planning-experimental` in its work card. Keep normal animation methods available. Neither enabling this method nor reviewing a candidate changes project defaults or approves replacement of existing clips.

The deliverable is an editable performance plan whose controls actually drive the detailed asset. Boxes drawn over an existing clip are a visualization, not evidence of this authoring method. Use the project's anatomy, art direction, scale, runtime and clip interfaces; do not transplant another creature's amplitudes or mannerisms.

## Coverage before motion

Inventory the source meshes, rig hierarchy, skin weights, morph families, accessories and textures. Record source identity, axes, dimensions, ground/contact convention, root-motion policy and intended viewing distance. Inspect the whole character from useful angles, including thin parts and the face.

Propose a coverage table before building clips. Account for every meaningful visible part and every deform bone/morph family, with an explicit independent, inherited, retained-procedural or deliberately-static policy. A box per bone is not required: grouped masses, IK targets, splines and shape sliders can express the anatomy better.

| Part / visible function | Control and mapping | Parent / attachment | Motion policy | Evidence |
| --- | --- | --- | --- | --- |
| Body masses | boxes and pivots → rig/deformation regions | root / spine | primary posture | rest and extremes |
| Eyes / lids, if present | gaze / blink → joints or shapes | head | independent acting | face closeup |
| Mouth / jaw | joint or shape controls | head | open / close without collapse | front and side extremes |
| Whiskers / antennae | roots and tips or spline | head, then segments | follow head plus local motion | head-turn test |
| Feet / contact surface | targets or deformation controls | explicit world/body policy | plant, swing or slide intentionally | low side view |
| Tail / fins / grips / props | anatomy-appropriate controls | named dependency | independent, inherited or intentionally still | primary and secondary motion |

The agent proposes coverage and a labeled rest/extreme sheet; do not rely on the user noticing omissions after the animation is complete. Missing eyelid geometry, mouth topology or usable weights are rig limitations, not problems a proxy box solves. Record them and make a scoped rig correction when authorized. Do not claim a complete facial performance when only body motion is available.

## Block a performance

For each clip, specify intent, duration, loop/one-shot, main beats, contact events, start/end state and transitions. Establish what leads and what follows. Block readable poses, then refine timing, anticipation, decisive action, attention and settling. Add secondary motion where it supports that intent. Uniform smoothing can erase urgency or weight; smoothness alone is not a quality verdict.

Place pivots at actual rotation centers and points at contacts. Label independent facial and appendage controls. Keep their dependencies explicit: a whisker root follows the head and has local acting of its own. Review primitive motion from at least two useful views before expanding the sweep. Preserve the controls and their actions as editable authoring inputs.

Use the studio-blender execution route appropriate to the task and the user's screen constraints. If an exploratory background blockout is needed, inspect rendered rest/extreme and motion evidence promptly and iterate; a single unreviewed generator run is not a finished performance.

## Transfer the same plan

Store rest-space mappings to bones, deformation regions, shape channels or contact targets. Evaluate local/world transforms and scale inheritance deliberately to avoid double transforms. A rotating child under nonuniform scale can acquire shear that bone TRS cannot reproduce. Where a rigid eye, valve or accessory must follow a stretched surface, use an anchor that follows the attachment position and rotation without inheriting stretch. Measure transfer error against the evaluated controls.

Bake evaluated motion into named export actions at the required sample rate. Preserve source geometry, weights and hierarchy when possible; separately identify any necessary rig/topology change. Export all required skinned meshes and morphs, excluding custom bone shapes and review helpers. Keep texture dependencies intact. After a plan edit, rerun transfer/export unless the rig retains live constraints; a baked rig does not automatically follow later box edits.

Inspect detailed-mesh rest and maximum bend, twist and compression before a large sweep. Check attachment drift, eye/mouth visibility, collapse, volume loss, folded limbs, interpenetration and sliding contacts. Compare feature motion ranges with the original to expose silently frozen parts; greater movement is not automatically better. Resolve defects within scope and disclose remaining limitations per clip.

## Fair comparison

Present original, candidate and primitive plan with synchronized phase, consistent camera, framing, lighting and sample rate. Preserve the source's actual first-key offset and runtime duration. Sample animation time directly; avoid duplicate loop endpoints in playback.

- **Matched duration:** original retimed to the candidate's authored duration, with both rates labeled. This compares poses and trajectories.
- **Original gameplay duration:** original at its gameplay timing and candidate retimed to that duration. This checks whether the performance still reads at the required speed.
- If authored durations match, the modes coincide. State that instead of inventing a second comparison.

Show at least two cycles for loops, full one-shots, relevant transitions and closeups for vulnerable attachments. Disclose whether original interior curves were reused, only endpoints were consulted, or revisions followed a baseline comparison. Freeze the first candidate before comparison when testing independent authorship. Exploratory comparisons are not causal proof that one workflow is superior.

## Validate, browse and hand off

Freshly reimport exports and check geometry/material/morph preservation, bones, names, durations, finite transforms, loop seams and transition interfaces. Inspect the reimport visually. Check ordinary input and transitions in the target runtime; numerical checks alone do not establish appealing motion or user acceptance.

Return the editable plan, transferred source, runtime candidate, clip and control tables, source/output hashes, comparisons, limitations and review status. Keep approved originals. If the project has a canonical fieldbook/catalog, append experimental animation rounds under existing model identities; preserve pins and prior verdicts. Make every clip discoverable there with its baseline and workflow identity rather than proliferating unrelated galleries. Registration is not adoption.

Keep clip verdicts unresolved until the human reviews them; allow improved / equivalent / worse / needs changes decisions per clip. Promotion to a project default is a separate explicit user decision, informed by repeated results across anatomies, deformation quality, gameplay timing and refinement effort.

## Portable invocation

> Use the experimental primitive-planning workflow in studio-animation for this model's animation sweep. First propose complete control coverage and clip intent using its own anatomy and rig. Preserve the approved asset. Build an editable primitive plan, inspect extremes, transfer it, and compare original/candidate/plan at matched and original gameplay durations. Include attachment and deformation checks, publish review candidates to our existing catalog, and report limitations. Keep this opt-in and leave production selections unchanged.

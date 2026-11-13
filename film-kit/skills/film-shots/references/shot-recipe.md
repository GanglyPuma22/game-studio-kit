# Shot recipe: one shot, one action

The unit of paid video generation (measured Nov 2026 on Kling 4 and Seedance 2.5). It replaced long chunk and single-pass renders after two independent reviews agreed: look and identity were solved, action was not, and a better single pass would not solve it. A video model plans one continuous scene and honours one or two actions per shot; a long prompt with timed beats is read as a list, not a schedule, so beats get reordered, merged or skipped.

## The unit

Every generation is **one camera setup, 3-5 s, with exactly one action** that runs forward from its first frame to its last.

- **One camera.** No cuts inside a generation. A new framing is a new shot.
- **One action.** "The hand closes round her" is one action. "Swing in, then slash" is two, and becomes two shots.
- **Contact happens inside a shot** as that shot's one action, when the film needs to see it (a grab). Otherwise it happens on a cut, and both shots agree on the state. A grab whose closing fell on the cut between two shots was never generated at all: the hand "closed around space".
- **Handles.** Generate 3 s or more, keep the best 0.6-2.5 s in the edit. Shots under 1.5 s are edit decisions, never their own generation.
- **Look is fixed in the edit.** The same references in every shot, one colour grade over the whole cut at the end.
- **A long camera move** (a flown reveal, a merged chase) splits at its [anchors](../../film-camera/references/rigs.md#rules-that-came-out-of-it) into back-to-back generations: each piece's last frame is the next piece's first, so the move plays as one flight.
- **Cut pieces at key events.** Models that take only a first and last frame control nothing in between, so every key moment (a stomp, a grab, a hit) must be a join frame between two pieces, where it is painted and pinned.

## Inputs

What each input does, the guide method and prompt anatomy are in [inputs](inputs.md). In short: painted first and last frames are the control, one sheet per character carries identity, one style frame carries the look, the layout with characters is staging only, and camera-heavy shots add a camera-only guide clip.

## Step by step

Nothing paid runs until all seven pre-run checks pass.

1. **Write the shot spec** (free), saved next to the job as `<shot>.spec.md`: film span, the one camera setup, the one action, what the first and last frames show (who, where, pose, hand and contact state), who is on screen and their sheets, guide video or none and why, and the pass line, written before the run.
2. **Fix the layout until it shows the action** (free, in the engine). The clay frames at the shot's start and end share the camera, and their difference is the action at a readable size. A grab failed this: the hand was beside her, not under her.
3. **Paint both frames in one session, from that layout** (free). Paint the last frame from the first plus the layout, so only the action changes. Never pair a frame from an old board with a new one: a grab job asked for curled-to-open because its two frames came from different sessions, and the model barely moved.
4. **Write the prompt from the spec**, never by hand. "It has not touched her yet" kept a grab apart.
5. **Same references every shot:** each on-screen character's sheet plus the style frame.
6. **Pre-run check** (free; a second reviewer reads only the spec and the two frames):
   1. Same camera in both frames (or the spec says how it moves).
   2. The difference between the frames *is* the action, and it runs forward.
   3. Every character on screen has its sheet attached; nobody else is named.
   4. The prompt matches the frames.
   5. The first frame joins the previous shot's last, and the last joins the next shot's first.
   6. Any contact happens inside a shot or exactly on a cut, never lost between them.
   7. 3-5 s, cost and cap stated, and the person typed the go.
7. **Run once, then QA** at 6-8 fps against the pass line: one of each character, the action in order, no frozen holds. Write the verdict on the shot card: pass, half or fail, and whether it was an input fault or a model limit.
8. **Retake only failing shots,** at most two takes each, changing one named input per retake.
9. **Edit:** trim handles, cut, per-shot colour match, one grade over the whole film, then sound.

## The shot card

One card per shot beside its job file, so any result traces back to what produced it: shot id and film times, camera, the one action, layout files, first and last frame with paint session and source, references, the exact prompt, model and settings and guide video, the pre-run check result with reviewer and date, cost, result file, verdict against the pass line, and the span used in the edit.

## Stop list

- single long passes for action (they reorder and drop beats);
- middle frames without a timestamp;
- plain pillar stand-ins for characters in a whole-scene pass (one character turned into a second copy of another);
- pairing frames from different paint sessions;
- shots under 1.5 s as their own generation;
- redesigning mid-film, and re-rendering shots that already pass.

## Cost (Kling 4.0 on fal, 720p, Nov 2026)

$0.157/s with no guide video (3 s = $0.47); with a guide video $0.094/s on guide plus output (5 s about $0.94). A whole 23-shot film this way is about $17 per pass, about $25 with retakes. Quote the cost per shot before asking for the go.

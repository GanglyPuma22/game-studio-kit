# Checks

What tells a usable take from a bad one, and where a bad one broke. Gates marked *proposed* are not yet run on every take; adopt them once the person agrees.

## Take gates

Run on every take, in this order. The first failure names the stage to fix.

| Gate | Tool | Pass | Stage it blames |
|---|---|---|---|
| Views agree | `python -m video2rig check <project> <clip>` | Body within 1.5% of its height between views; limbs over about 4% need a look at the legs (one take was kept at 4.7%, another failed at 4.0%) | Video: reroll, never fit |
| Colours held | Eyeball the frame sheet | No limb colour swaps or fades; the same creature in both panels | Video |
| Reader confidence | Read log | Mean confidence within 0.05 of the move's best take (0.60 Seedance punch, 0.68 Kling 2.6 punch) | Video or reader |
| Pops | `despike.py --deg 20 --k 3` report | No more than 2 more one-to-three-frame pops than the best take; 0 is normal after the first-guess fix | Fit first, then reader |
| Max joint turn per frame | Fit report | Under about 25 degrees a frame on every joint (the heave went from 231 to 22 with the first-guess fix) | Fit |
| Feet | Bake log | Soles never under the floor; frames under the floor counted (Kling 2.6 punch: 22) | Fit (floor weight) |
| Eyes | Side-by-side preview | The person says it matches the video and reads as the move | Any |

A pass is a shortlist, not a yes. Numbers miss a punch that reads as a lean.

## Take ledger

*Proposed.* One CSV per character, one row per generated clip, pass or fail, so pass rates and cost per usable move are known instead of remembered from threads:

```
date,character,move,take,model,seed,prompt_file,start_picture,reader,cost,check_pct,conf,pops,max_deg_frame,result,why,preview
```

Keep the prompt file and start picture paths exact, so a take can be reproduced. `result` is one of `keep`, `shortlist`, `fail`, `flagged` (a near miss kept aside). Six `fail` rows for one move stop spending on it.

## Exam

*Proposed.* Separates reader error from fit error with no video and no spend. Make a known motion inside the joint limits that includes the hard poses for this character (arms overhead, a hidden forearm, a deep crouch). Render it through the start cameras in the colour suit, read it with the character's reader, fit it, and compare joints to the truth in centimetres and joint angles in degrees.

- Reader error = reader's 2D points vs true projected joints.
- Fit error = fitted joints vs true joints, on the same readings.

Run it whenever the reader, rig, limits or fit rules change. Anymove's `mocap/exam.py` (Apache-2.0) is a model to follow; its wolf scored 0.94 cm mean on a 1.6 m body. Writing our own version for video2rig's outputs keeps the AGPL rule.

## Headroom

The biggest pose of every planned move must fit both panels with margin: height under about 0.85 of the ground row's height in metres, width under the front panel, length under the side panel. Check it against the move card before rendering the start picture. Overhead lifts and long reaches leave the frame or cross the divider when this is skipped.

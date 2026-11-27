# Keep or kill

Review a result against its [direction sheet](../../../templates/direction-sheet.md). Any "no" kills the take or sends it back with the failed decision named. Record each row's answer and the frame or time that shows it. A killed take adds its failure noun to the sheet's avoid-list (D7) before the next round, and the next round changes one thing.

Rows for a waived decision are answered "waived" with the sheet's reason.

## In-engine

Judge in the game's own renderer, at the player's usual and closest distances, at full speed and frame-stepped at the game's tick. Look from the actor's camera and from the receiving player's camera.

| # | Decision | Keep only if |
|---|---|---|
| 1 | D2 | You can name the one moment, and damage, burst, sound and hit-stop land on the same frame (one key or event, checked frame by frame) |
| 2 | D3 | The anticipation silhouette differs from rest and reads at full speed from the receiving player's camera |
| 3 | D3 | The anticipation length equals the tuning value on the sheet; the look pass did not change it |
| 4 | D3 | The release is the fastest phase, and the move settles with an overshoot instead of cutting to idle |
| 5 | D4 | Smears appear only on the fastest 1 or 2 frames; locomotion, blends, camera and telegraphs are not stepped |
| 6 | D5 | The gameplay event is the brightest, highest-contrast thing in frame at its moment; ambient effects sit below it |
| 7 | D5 | No effect hides a telegraph, a character's silhouette, a landing zone or another character |
| 8 | D1 | Effect colours match the named swatches (sample pixels from a capture; don't compare against memory) |
| 9 | D7 | No avoid-list noun is visible |
| 10 | D6 | A directed loop has no findable seam at full speed; a one-shot does not loop |
| 11 | Limits | Information a player reacts to comes from synced state; cosmetic particles carry none of it |
| 12 | Limits | No camera impulse beyond the game's camera settings |
| 13 | Limits | Each new emitter's amount and lifetime are within the sheet's budget, measured in a capture |

## Video

Judge frame-stepped at 6 to 8 fps and again at full speed.

| # | Decision | Keep only if |
|---|---|---|
| 1 | D2 | You can name the one moment, and it lands within about 0.3 s of its directed time |
| 2 | D3 | The 3 to 5 frames before the hit differ from rest (a readable anticipation) |
| 3 | D3 | The action settles, instead of stopping dead or jittering on |
| 4 | D5 | In the first frame and at the moment, the focal point is the brightest, highest-contrast element |
| 5 | D1 | The palette matches the locked swatches (sample the pixels) |
| 6 | D7 | No avoid-list noun is visible (blob, muddiness, proportion drift, extra limbs, mush) |
| 7 | D6 | A directed loop has no seam findable at full speed |
| 8 | D4 | If on-twos was directed, frame-stepping shows held poses, not smooth interpolation throughout |

# Operational studio-review implementation

Accepted scope: execute the existing review workflow with immutable card/run evidence,
an owned FFmpeg recorder, a bounded Gemini video request, evidence-bound decisions,
and a comparable affected recheck. No game edits or native/provider operation is
implicitly authorized. Public examples are original and anonymous.

1. Add failing behavioral tests for card identity, launch intent, stale evidence,
   lifecycle normal/cancel/timeout/start failure, temporal false passes and budget ambiguity.
2. Implement strict card/run helpers using existing evidence utilities and verdicts;
   extend owned processes only for graceful recorder stop. Probe/decode actual media.
3. Add an explicit FFmpeg file/native Windows capture profile and Gemini static video
   plus dense PTS frame adapter. Preserve complete raw responses and request reservations;
   stop on ambiguous outcomes. Never infer perception from installation or mocks.
4. Generate original clean/100ms/single-frame/stutter/drop/interaction/audio fixtures,
   keep truth annotations outside prompts, run real local encoder/decoder roundtrips.
5. Connect CLI, doctor and concise skill procedure; run required suite/package check,
   self-review, commit and deliver capability gaps plus a <=20 minute native proposal.

Verification: targeted unittest cases followed by full unittest discovery and
check-package. Native capture/held controls, listening and model fixture detection
remain explicitly pending until independently demonstrated with actual authorization.

Executed: 23 new behavioral tests plus the 122-test baseline. Real installed
FFmpeg/FFprobe generated and decoded the eight original controls. The file example
retains an injected wall-time failure and a matched clean affected recheck, while
TEMP/SOUND remain unverified. Full suite: 145 tests, OK (two native skips). Package
resource omission found by full-suite validation was corrected. Native recorder,
held inputs, actual Gemini detection and listening remain pending authorization
and independent acceptance. No provider/native operation or production mutation.

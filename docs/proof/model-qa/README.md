# Model QA proof

Three external model families are identified by their input SHA-256 hashes in
[provenance.json](provenance.json). Project-specific names and source locations
are intentionally absent from this generic kit. The private lane handoff holds
the source mapping. Only display labels were anonymized; part IDs, bounds,
counts, input hashes, measurements and failure verdicts are unchanged.

| Specimen | LOD triangles | Budget | M12 | M13 |
|---|---|---:|---|---|
| [A](specimen-a/REPORT.md) | 10442 / 5931 / 3917 | 5000 | PASS at every LOD | PASS at every LOD |
| [B](specimen-b/REPORT.md) | 7288 / 4310 / 2890 | 5000 | PASS at every LOD | PASS; LOD0 has one allowed minor pair |
| [C](specimen-c/REPORT.md) | 4400 / 2028 / 1378 | 2000 | PASS at every LOD | PASS at every LOD |

Every **combined report is FAIL**. Some triangle budgets fail, the supplied
source has no ecology entry or switch distances, and diagnostic silhouettes
change by 14.7–26.2% XOR/union at the automatically recorded fallback distances.
No fallback distance is presented as a game switch distance. Correspondence
flags are candidates for missing or substantially simplified parts, not a
claim that every flagged part was deleted.

[Reference parity](reference-parity.json) reran the original checkers and the
port on exactly the same 18 GLBs: nine external LODs, eight static synthetic
fixtures and one animated skin fixture. All verdicts and measured failing
part/pair identities agree. M13 parity applies to static models because the
reference clipping checker is static. The skinned M12 reference is sampled
at rest and throughout the synthetic detach clip.

[Validation](validation.json) records the eight passing focused tests, the
full suite's failures, and the 15 failures reproduced on the unmodified base.
The remaining new resource-manifest failure is documented in the
[lane result](../../../codex-out/model-qa/RESULT.md), with an unapplied patch
because this lane may only add files.

The contact sheets use a shared center crop with a labelled pixel scale.
The original 1920x1080 binary silhouettes are included next to each report.
They are geometric evidence, not material/alpha rendering or human acceptance.
The later contact-sheet layout change left all report measurements identical;
the numerical check modules retain the parity run's exact byte hashes.

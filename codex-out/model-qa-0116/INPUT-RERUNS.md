# Unchanged-input comparison

26 families, 74 identical GLBs; private mapping and full reports retained locally.
The table preserves raw row-state transitions; old FAIL can mean an unsupported/unmeasured input, not a measured defect.
All thresholds, sample counts and resolution remain unchanged. All switch sets remain absent, so M5 cannot qualify.

| Check transition | LOD rows |
|---|---:|
| M12: FAIL -> FAIL | 14 |
| M12: FAIL -> PASS | 13 |
| M12: FAIL -> UNMEASURED | 7 |
| M12: PASS -> PASS | 40 |
| M13: FAIL -> FAIL | 17 |
| M13: FAIL -> PASS | 9 |
| M13: FAIL -> UNMEASURED | 8 |
| M13: PASS -> PASS | 40 |
| M5: FAIL -> FAIL | 63 |
| M5: FAIL -> UNMEASURED | 11 |
| ecology: FAIL -> N/A | 42 |
| ecology: FAIL -> PASS | 32 |
| triangles: FAIL -> FAIL | 1 |
| triangles: FAIL -> NOT SET | 40 |
| triangles: FAIL -> PASS | 15 |
| triangles: FAIL -> UNMEASURED | 6 |
| triangles: PASS -> PASS | 12 |

## Strict-default reruns

| Family | LODs | Overall | States |
|---|---:|---|---|
| family-01 | 2 | FAIL | {'FAIL': 2, 'PASS': 8} |
| family-02 | 5 | FAIL | {'FAIL': 13, 'PASS': 12} |
| family-03 | 4 | FAIL | {'FAIL': 9, 'N/A': 4, 'NOT SET': 4, 'PASS': 3} |
| family-04 | 4 | FAIL | {'FAIL': 4, 'PASS': 16} |
| family-05 | 4 | FAIL | {'FAIL': 4, 'PASS': 16} |
| family-06 | 4 | FAIL | {'FAIL': 4, 'N/A': 4, 'NOT SET': 4, 'PASS': 8} |
| family-07 | 4 | FAIL | {'FAIL': 8, 'N/A': 4, 'NOT SET': 4, 'PASS': 4} |
| family-08 | 4 | FAIL | {'FAIL': 4, 'N/A': 4, 'NOT SET': 4, 'PASS': 8} |
| family-09 | 4 | FAIL | {'FAIL': 4, 'N/A': 4, 'NOT SET': 4, 'PASS': 8} |
| family-10 | 4 | FAIL | {'FAIL': 4, 'N/A': 4, 'NOT SET': 4, 'PASS': 8} |
| family-11 | 4 | FAIL | {'FAIL': 4, 'N/A': 4, 'NOT SET': 4, 'PASS': 8} |
| family-12 | 4 | FAIL | {'FAIL': 9, 'N/A': 4, 'NOT SET': 4, 'PASS': 3} |
| family-13 | 4 | FAIL | {'FAIL': 4, 'N/A': 4, 'NOT SET': 4, 'PASS': 8} |
| family-14 | 1 | FAIL | {'FAIL': 3, 'N/A': 1, 'PASS': 1} |
| family-15 | 1 | FAIL | {'FAIL': 3, 'PASS': 2} |
| family-16 | 1 | FAIL | {'FAIL': 2, 'PASS': 3} |
| family-17 | 1 | FAIL | {'FAIL': 3, 'PASS': 2} |
| family-18 | 1 | FAIL | {'FAIL': 3, 'N/A': 1, 'PASS': 1} |
| family-19 | 1 | FAIL | {'FAIL': 1, 'N/A': 1, 'NOT SET': 1, 'PASS': 2} |
| family-20 | 1 | FAIL | {'FAIL': 1, 'N/A': 1, 'NOT SET': 1, 'PASS': 2} |
| family-21 | 1 | FAIL | {'FAIL': 1, 'N/A': 1, 'NOT SET': 1, 'PASS': 2} |
| family-22 | 1 | FAIL | {'FAIL': 1, 'N/A': 1, 'NOT SET': 1, 'PASS': 2} |
| family-23 | 4 | UNMEASURED | {'PASS': 5, 'UNMEASURED': 15} |
| family-24 | 4 | UNMEASURED | {'FAIL': 1, 'PASS': 5, 'UNMEASURED': 14} |
| family-25 | 3 | FAIL | {'FAIL': 3, 'PASS': 12} |
| family-26 | 3 | UNMEASURED | {'PASS': 12, 'UNMEASURED': 3} |

## Explicit provisional applicability experiments

These sidecar declarations demonstrate the new contracts. They are not approvals of project metadata or terrain placement.
Raw M13 measurements are identical to the matching strict reruns. Ground contact uses a declared Y=0 plane at 3 mm.

| Family | LOD | M12 strict → ground | M13 strict → declared | Off-plane pieces |
|---|---:|---|---|---:|
| family-07 | 0 | PASS → PASS | FAIL → INFO | 0 / 57 |
| family-07 | 1 | PASS → PASS | FAIL → INFO | 0 / 30 |
| family-07 | 2 | PASS → PASS | FAIL → INFO | 0 / 30 |
| family-07 | 3 | PASS → PASS | FAIL → INFO | 0 / 21 |
| family-14 | 0 | FAIL → FAIL | PASS → INFO | 258 / 398 |
| family-15 | 0 | FAIL → FAIL | FAIL → INFO | 96 / 96 |
| family-16 | 0 | PASS → FAIL | FAIL → INFO | 96 / 96 |
| family-17 | 0 | FAIL → FAIL | FAIL → INFO | 36 / 36 |
| family-18 | 0 | FAIL → FAIL | FAIL → INFO | 4 / 8 |
| family-12 | 0 | FAIL → PASS | PASS → PASS | 0 / 33 |
| family-12 | 1 | FAIL → PASS | FAIL → FAIL | 0 / 33 |
| family-12 | 2 | FAIL → PASS | PASS → PASS | 0 / 33 |
| family-12 | 3 | FAIL → PASS | PASS → PASS | 0 / 24 |

# Preparing a distinct local plugin version

Use a complete, separate staging copy when the host's install flow needs a distinct
cache version. Keep the reviewed checkout and installed caches unchanged. Record
the source commit before copying. Change both `.codex-plugin/plugin.json` and
`studio-kit.json` to the same staging version; `check-package` deliberately requires
equality. Python's semantic package version remains the source release version.

Save the following code as a temporary host script outside KIT and run:

```text
python <HOST_SCRIPT> <STAGED_KIT> 0.1.1+staging.1 <RECEIPT_OUTSIDE_KIT> <SOURCE_COMMIT>
python <STAGED_KIT>/scripts/studio.py check-package --root <STAGED_KIT>
```

The source commit is supplied by the operator; the receipt attests the actual
before/after file hashes and packaging delta, not an independently verified Git
relationship. Run only against the new staging copy. A failed stage is incomplete
and must not be installed.

```python
import hashlib
import json
from pathlib import Path
import sys

kit = Path(sys.argv[1]).resolve()
version = sys.argv[2]
receipt = Path(sys.argv[3]).resolve()
revision = sys.argv[4]
if not version or receipt.is_relative_to(kit):
    raise ValueError("Supply a version and a new receipt path outside the staged kit")
names = (".codex-plugin/plugin.json", "studio-kit.json")
originals = {name: (kit / name).read_bytes() for name in names}
records = {name: json.loads(data) for name, data in originals.items()}
versions = {record["version"] for record in records.values()}
if len(versions) != 1:
    raise ValueError("Source declarations disagree; restage from the reviewed source")
result = {"source_revision": revision, "source_version": versions.pop(),
          "staged_version": version, "files": {}}
receipt.parent.mkdir(parents=True, exist_ok=True)
with receipt.open("x", encoding="utf-8") as output:
    for name, record in records.items():
        record["version"] = version
        data = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        (kit / name).write_bytes(data)
        result["files"][name] = {
            "before_sha256": hashlib.sha256(originals[name]).hexdigest(),
            "after_sha256": hashlib.sha256((kit / name).read_bytes()).hexdigest()}
    json.dump(result, output, indent=2)
    output.write("\n")
```

From GAME, check the staged KIT through its absolute helper. Record module paths
and hashes from the actual installed copy when verifying adoption. Preserve all
bytes in candidate workflow inventories, including `.codex-plugin/plugin.json`:
the staged copy has a different workflow digest from its source commit. Retain
the receipt alongside validation evidence to explain that difference. Do not
normalize away version bytes or rewrite historical candidate digests. Installing
or refreshing the host's registered plugin is a separate authorized host action.

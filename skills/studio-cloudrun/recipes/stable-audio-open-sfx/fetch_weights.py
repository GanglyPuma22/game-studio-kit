"""Download the staged model files and check each SHA-256. weights.json comes
from the host (stage_hf.py): per file either a short-lived link or the bytes
inline (small config files). Exits non-zero on any mismatch."""
import base64, hashlib, json, os, sys, time, urllib.request
from pathlib import Path

manifest, dest = json.load(open(sys.argv[1])), Path(sys.argv[2])
t0 = time.time()
total = 0
for f in manifest["files"]:
    out = dest / f["path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    if "inline_b64" in f:
        data = base64.b64decode(f["inline_b64"])
        out.write_bytes(data)
        h.update(data)
    else:
        with urllib.request.urlopen(f["url"], timeout=120) as r, out.open("wb") as w:
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                w.write(block)
                h.update(block)
    if h.hexdigest() != f["sha256"]:
        sys.exit(f"SHA-256 mismatch for {f['path']}")
    total += out.stat().st_size
os.remove(sys.argv[1])  # the links are capabilities; drop them once used
print(f"weights ok: {len(manifest['files'])} files, {total} bytes, {time.time() - t0:.1f} s, {manifest['repo']}@{manifest['revision']}")

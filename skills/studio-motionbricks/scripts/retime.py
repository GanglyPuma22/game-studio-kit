"""Retime played frames piecewise to the game's grab timings (quaternion slerp between frames).
python -I retime.py <frames.npy> <labels.json> <out.npy> <out_labels.json> seg_seconds...
Segments are the label boundaries in order (rest+P1, P2, P3, P4, P0)."""
import sys, json, numpy as np
from scipy.spatial.transform import Rotation as R, Slerp
fr = np.load(sys.argv[1]); lab = json.load(open(sys.argv[2]))
secs = [float(v) for v in sys.argv[5:]]
bounds = sorted(int(k) for k in lab if k not in ("contact", "0"))
edges = [0] + bounds[1:] + [len(fr) - 1]
out, newlab, contact = [], {}, lab["contact"]
names = [lab[str(b)] for b in bounds]
for si, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
    n = max(2, int(round(secs[si] * 30)))
    newlab[str(len(out))] = names[si] + f" ({secs[si]:.2f} s)"
    for k in range(n):
        t = a + (b - a) * k / n
        i = int(np.floor(t)); u = t - i; j = min(i + 1, len(fr) - 1)
        if a <= contact < b and i <= contact <= j and "contact" not in newlab:
            newlab["contact"] = len(out)
        pose = fr[i].copy()
        pose[:, :3] = fr[i][:, :3] * (1 - u) + fr[j][:, :3] * u
        for jn in range(fr.shape[1]):
            q = R.from_quat([fr[i][jn, 3:], fr[j][jn, 3:]])
            pose[jn, 3:] = Slerp([0, 1], q)([u]).as_quat()[0]
        out.append(pose)
newlab.setdefault("contact", int([k for k, v in newlab.items() if v.startswith("to P3")][0]))
out.append(fr[-1])
np.save(sys.argv[3], np.stack(out)); json.dump(newlab, open(sys.argv[4], "w"))
print(len(out), "frames", newlab)

"""Draw SOMA poses as a stick figure from two views (side and front three-quarter).

stills: python -I render.py stills <poses.npz> <out.png> P0 P1 ...
video : python -I render.py video <frames.npy> <poses.npz> <out.mp4> [labels.json]
"""
import sys, os, json, subprocess, tempfile
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation as R

HERE = os.path.dirname(os.path.abspath(__file__))
PAR = None


def fk(pose):
    n = len(pose)
    pos = np.zeros((n, 3)); rot = [None] * n
    for i in range(n):
        lq = R.from_quat(pose[i, 3:])
        p = PAR[i]
        if p < 0:
            pos[i], rot[i] = pose[i, :3], lq
        else:
            pos[i] = pos[p] + rot[p].apply(pose[i, :3]); rot[i] = rot[p] * lq
    return pos


RIGHT_SIDE = None
LEFT_SIDE = None


def palm(pos):
    """The right hand's palm normal (out of the palm) from the finger roots."""
    h = pos[NAMES.index("RightHand")]; m = pos[NAMES.index("RightHandMiddle1")]
    i = pos[NAMES.index("RightHandIndex1")]; k = pos[NAMES.index("RightHandPinky1")]
    f = (m - h) / np.linalg.norm(m - h)
    n = np.cross(i - k, f); n -= f * np.dot(n, f)
    return m, n / np.linalg.norm(n)


def _target(z):
    """The point the pose aims at (key "target", or "warden" in older files), if any."""
    for k in ("target", "warden"):
        if k in z:
            return z[k]
    return None


def draw(ax, pos, view, fwd, right, target=None, title=""):
    # project: view "side" looks along -right (character's right toward camera's left), "front34"
    up = np.array([0, 1.0, 0])
    if view == "side":
        h_axis = fwd
    else:
        h_axis = (right * 0.8 - fwd * 0.6); h_axis /= np.linalg.norm(h_axis)
    o = pos[0] * np.array([1, 0, 1])
    def P(p):
        d = p - o
        return np.dot(d, h_axis), d[1]
    for i, p in enumerate(PAR):
        if p < 0:
            continue
        name = NAMES[i]
        if any(k in name for k in ("Eye", "Jaw")):
            continue
        a, b = P(pos[p]), P(pos[i])
        col = "#d1495b" if name.startswith("Right") else ("#2e86ab" if name.startswith("Left") else "#333333")
        lw = 1.0 if "Hand" in name and not name.endswith("Hand") else 3.0
        ax.plot([a[0], b[0]], [a[1], b[1]], color=col, lw=lw, solid_capstyle="round")
    m, n = palm(pos)
    a, b = P(m), P(m + n * 0.12)
    ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="->", color="#f4a259", lw=1.6))
    if target is not None:
        w = P(target)
        ax.plot([w[0]], [w[1]], "o", color="#3bb273", ms=9)
    ax.axhline(0, color="#999", lw=1)
    ax.set_xlim(-1.1, 1.3); ax.set_ylim(-0.05, 2.0); ax.set_aspect("equal"); ax.axis("off")
    if title:
        ax.set_title(title, fontsize=10)


def main():
    global PAR, NAMES
    mode = sys.argv[1]
    if mode == "stills":
        z = np.load(sys.argv[2]); out = sys.argv[3]; keys = sys.argv[4:]
        PAR = np.load(os.path.join(os.path.dirname(sys.argv[2]), "parents.npy"))
        NAMES = json.load(open(os.path.join(os.path.dirname(sys.argv[2]), "names.json")))
        fig, axes = plt.subplots(2, len(keys), figsize=(2.6 * len(keys), 5.2))
        for c, k in enumerate(keys):
            pos = fk(z[k])
            draw(axes[0, c], pos, "side", z["fwd"], z["right"], _target(z), k + " side")
            draw(axes[1, c], pos, "front34", z["fwd"], z["right"], _target(z), k + " 3/4")
        fig.tight_layout(); fig.savefig(out, dpi=110)
    else:
        frames = np.load(sys.argv[2]); z = np.load(sys.argv[3]); out = sys.argv[4]
        labels = json.load(open(sys.argv[5])) if len(sys.argv) > 5 else {}
        PAR = np.load(os.path.join(os.path.dirname(sys.argv[3]), "parents.npy"))
        NAMES = json.load(open(os.path.join(os.path.dirname(sys.argv[3]), "names.json")))
        tmp = tempfile.mkdtemp()
        fig, axes = plt.subplots(1, 2, figsize=(8, 4.2))
        for f in range(len(frames)):
            for ax in axes:
                ax.clear()
            pos = fk(frames[f])
            lab = ""
            contact = labels.get("contact", 10 ** 9)
            for k, v in labels.items():
                if k == "contact":
                    continue
                if f >= int(k):
                    lab = v
            w = _target(z)
            if f >= contact:
                m, n = palm(pos)
                w = m + n * 0.05
            draw(axes[0], pos, "side", z["fwd"], z["right"], w, "side")
            draw(axes[1], pos, "front34", z["fwd"], z["right"], w, "3/4 front")
            fig.suptitle(f"{lab}   frame {f}  ({f / 30:.2f} s)    orange arrow = palm faces, green = target", fontsize=10)
            fig.savefig(f"{tmp}/f{f:04d}.png", dpi=100)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "30", "-i", f"{tmp}/f%04d.png",
                        "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", out], check=True)


if __name__ == "__main__":
    main()

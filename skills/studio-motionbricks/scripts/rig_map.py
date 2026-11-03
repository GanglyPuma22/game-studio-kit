"""Move poses between the SOMA skeleton (MotionBricks) and a game humanoid skeleton
(here UE/Quaternius-style names: pelvis, spine_01, upperarm_l ...), both ways.
Edit PAIRS for another naming scheme.

Each mapped bone copies the other rig's world turn away from its rest pose,
after a swing that lines the two rests' bone directions up (so a T-pose and
an A-pose rest both work). Both rigs are Y up and face +Z.

Game rig data comes from dump_skeleton.gd: rest and frames as world (skeleton
space) [x, y, z, qx, qy, qz, qw] per bone.
"""
import numpy as np
from scipy.spatial.transform import Rotation as R

# canonical name: (soma joint, game bone, child used for the bone's direction)
PAIRS = {
    "hips": ("Hips", "pelvis", "spine1"),
    "spine1": ("Spine1", "spine_01", "spine2"),
    "spine2": ("Spine2", "spine_02", "chest"),
    "chest": ("Chest", "spine_03", "neck"),
    "neck": ("Neck1", "neck_01", "head"),
    "head": ("Head", "Head", None),
}
for s, w in (("Left", "l"), ("Right", "r")):
    PAIRS.update({
        f"clav_{w}": (f"{s}Shoulder", f"clavicle_{w}", f"arm_{w}"),
        f"arm_{w}": (f"{s}Arm", f"upperarm_{w}", f"fore_{w}"),
        f"fore_{w}": (f"{s}ForeArm", f"lowerarm_{w}", f"hand_{w}"),
        f"hand_{w}": (f"{s}Hand", f"hand_{w}", f"mid_{w}"),
        f"mid_{w}": (f"{s}HandMiddle1", f"middle_01_{w}", None),
        f"leg_{w}": (f"{s}Leg", f"thigh_{w}", f"shin_{w}"),
        f"shin_{w}": (f"{s}Shin", f"calf_{w}", f"foot_{w}"),
        f"foot_{w}": (f"{s}Foot", f"foot_{w}", f"toe_{w}"),
        f"toe_{w}": (f"{s}ToeBase", f"ball_{w}", f"toeend_{w}"),
        f"toeend_{w}": (f"{s}ToeEnd", f"ball_leaf_{w}", None),
    })
# Bones that only give a direction (their own turn is not copied).
DIR_ONLY = {"mid_l", "mid_r", "toeend_l", "toeend_r"}


def soma_fk(par, local):
    n = len(local); pos = np.zeros((n, 3)); rot = [None] * n
    for i in range(n):
        lq = R.from_quat(local[i, 3:]); p = par[i]
        if p < 0:
            pos[i], rot[i] = local[i, :3], lq
        else:
            pos[i] = pos[p] + rot[p].apply(local[i, :3]); rot[i] = rot[p] * lq
    return pos, rot


def _swing(a, b):
    """Shortest turn taking direction a onto b."""
    a = a / np.linalg.norm(a); b = b / np.linalg.norm(b)
    ax = np.cross(a, b); s = np.linalg.norm(ax)
    if s < 1e-9:
        return R.identity()
    return R.from_rotvec(ax / s * np.arctan2(s, np.dot(a, b)))


class RigMap:
    def __init__(self, soma_names, soma_par, soma_ref_local, w_bones, w_par, w_rest):
        self.sn = list(soma_names); self.si = {n: i for i, n in enumerate(self.sn)}
        self.spar = np.asarray(soma_par, int); self.sref = np.asarray(soma_ref_local, float)
        self.wn = list(w_bones); self.wi = {n: i for i, n in enumerate(self.wn)}
        self.wpar = list(w_par); self.wrest = np.asarray(w_rest, float)
        sp, sr = soma_fk(self.spar, self.sref)
        self.s_rest_pos, self.s_rest_rot = sp, sr
        self.w_rest_pos = self.wrest[:, :3]
        self.w_rest_rot = [R.from_quat(q) for q in self.wrest[:, 3:]]
        # Leg length for the hips' travel.
        self.s_leg = np.linalg.norm(sp[self.si["LeftLeg"]] - sp[self.si["LeftFoot"]])
        wl = self.w_rest_pos
        self.w_leg = np.linalg.norm(wl[self.wi["thigh_l"]] - wl[self.wi["foot_l"]])
        # Rest directions, and the swing from each rig's rest onto the other's.
        self.align_ws, self.align_sw = {}, {}
        for c, (sj, wb, ch) in PAIRS.items():
            if ch is None:
                self.align_ws[c] = R.identity(); self.align_sw[c] = R.identity(); continue
            ds = sp[self.si[PAIRS[ch][0]]] - sp[self.si[sj]]
            dw = wl[self.wi[PAIRS[ch][1]]] - wl[self.wi[wb]]
            self.align_ws[c] = _swing(dw, ds)    # game rest dir -> soma rest dir
            self.align_sw[c] = _swing(ds, dw)

    # ---------------------------------------------------------- soma -> game
    def to_game(self, soma_local, fill_local=None):
        """World rotations [B] (Rotation) and pelvis position for the game rig.
        fill_local: game rig local quats [B,4] for unmapped bones (fingers, blades)."""
        sp, sr = soma_fk(self.spar, soma_local)
        world = [None] * len(self.wn)
        by_w = {wb: c for c, (sj, wb, ch) in PAIRS.items() if c not in DIR_ONLY}
        for i, name in enumerate(self.wn):
            c = by_w.get(name)
            p = self.wpar[i]
            if c is not None:
                si = self.si[PAIRS[c][0]]
                dq = sr[si] * self.s_rest_rot[si].inv()
                world[i] = dq * self.align_ws[c] * self.w_rest_rot[i]
            else:
                if fill_local is not None:
                    loc = R.from_quat(fill_local[i])
                else:
                    pr = self.w_rest_rot[p] if p >= 0 else R.identity()
                    loc = pr.inv() * self.w_rest_rot[i]
                world[i] = (world[p] if p >= 0 else R.identity()) * loc
        hips = sp[self.si["Hips"]] - self.s_rest_pos[self.si["Hips"]]
        pelvis = self.w_rest_pos[self.wi["pelvis"]] + hips * (self.w_leg / self.s_leg)
        return world, pelvis

    def game_local(self, world):
        out = np.zeros((len(self.wn), 4))
        for i in range(len(self.wn)):
            p = self.wpar[i]
            loc = world[i] if p < 0 else world[p].inv() * world[i]
            out[i] = loc.as_quat()
        return out

    # ---------------------------------------------------------- game -> soma
    def to_soma(self, w_frame):
        """A SOMA local pose [J,7] from one game rig frame (world xf per bone)."""
        w_frame = np.asarray(w_frame, float)
        wrot = [R.from_quat(q) for q in w_frame[:, 3:]]
        by_s = {sj: c for c, (sj, wb, ch) in PAIRS.items() if c not in DIR_ONLY}
        world = [None] * len(self.sn)
        out = self.sref.copy()
        for i, name in enumerate(self.sn):
            p = self.spar[i]
            c = by_s.get(name)
            if c is not None:
                wi = self.wi[PAIRS[c][1]]
                dq = wrot[wi] * self.w_rest_rot[wi].inv()
                world[i] = dq * self.align_sw[c] * self.s_rest_rot[i]
            else:
                world[i] = (world[p] if p >= 0 else R.identity()) * R.from_quat(self.sref[i, 3:])
            loc = world[i] if p < 0 else world[p].inv() * world[i]
            out[i, 3:] = loc.as_quat()
        pel = w_frame[self.wi["pelvis"], :3] - self.w_rest_pos[self.wi["pelvis"]]
        out[self.si["Hips"], :3] = self.sref[self.si["Hips"], :3] + pel * (self.s_leg / self.w_leg)
        return out

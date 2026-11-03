"""Numpy pose tools for the 77-joint SOMA skeleton: forward kinematics, world-space
joint turns, two-bone IK with an explicit elbow/knee direction, and hand aiming.

A pose is an array [J, 7] of local transforms (px, py, pz, qx, qy, qz, qw), the same
layout as warp transforms. Model space: Y up, metres.
"""
import numpy as np
from scipy.spatial.transform import Rotation as R


def qmul(a, b):
    return (R.from_quat(a) * R.from_quat(b)).as_quat()


class Soma:
    def __init__(self, skeleton):
        self.par = skeleton.parent_indices.numpy().astype(int)
        self.names = [skeleton.joint_name(i) for i in range(skeleton.num_joints)]
        self.idx = {n: i for i, n in enumerate(self.names)}
        self.n = len(self.names)

    def j(self, name):
        return self.idx[name]

    def fk(self, pose):
        """World positions [J,3] and rotations (list of Rotation)."""
        pos = np.zeros((self.n, 3))
        rot = [None] * self.n
        for i in range(self.n):
            lp, lq = pose[i, :3], R.from_quat(pose[i, 3:])
            p = self.par[i]
            if p < 0:
                pos[i], rot[i] = lp, lq
            else:
                pos[i] = pos[p] + rot[p].apply(lp)
                rot[i] = rot[p] * lq
        return pos, rot

    def set_world_rot(self, pose, name, world_rot):
        i = self.j(name)
        _, rot = self.fk(pose)
        p = self.par[i]
        local = world_rot if p < 0 else rot[p].inv() * world_rot
        pose[i, 3:] = local.as_quat()

    def turn(self, pose, name, axis, deg):
        """Turn a joint (and its children) about a world axis through the joint."""
        _, rot = self.fk(pose)
        r = R.from_rotvec(np.asarray(axis, float) / np.linalg.norm(axis) * np.radians(deg))
        self.set_world_rot(pose, name, r * rot[self.j(name)])

    def aim(self, pose, name, child, goal):
        """Minimal turn so the bone name->child points at goal."""
        pos, rot = self.fk(pose)
        a = pos[self.j(child)] - pos[self.j(name)]
        b = goal - pos[self.j(name)]
        a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
        ax = np.cross(a, b)
        s = np.linalg.norm(ax)
        if s < 1e-8:
            return
        ang = np.arctan2(s, np.dot(a, b))
        r = R.from_rotvec(ax / s * ang)
        self.set_world_rot(pose, name, r * rot[self.j(name)])

    def two_bone(self, pose, root, mid, end, target, bend_dir):
        """Place end at target (clamped to reach); mid bends toward bend_dir."""
        pos, _ = self.fk(pose)
        a, b, c = pos[self.j(root)], pos[self.j(mid)], pos[self.j(end)]
        l1, l2 = np.linalg.norm(b - a), np.linalg.norm(c - b)
        d = target - a
        dist = np.clip(np.linalg.norm(d), abs(l1 - l2) + 1e-3, l1 + l2 - 1e-3)
        dn = d / np.linalg.norm(d)
        cos1 = (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist)
        h = l1 * np.sqrt(max(0.0, 1 - cos1 * cos1))
        pole = np.array(bend_dir, float)
        pole = pole - dn * np.dot(pole, dn)
        pole /= np.linalg.norm(pole)
        elbow = a + dn * l1 * cos1 + pole * h
        self.aim(pose, root, mid, elbow)
        self.aim(pose, mid, end, a + dn * dist)

    def hand_frame(self, pose, side):
        """Unit finger direction and palm normal (pointing out of the palm)."""
        pos, _ = self.fk(pose)
        h = pos[self.j(f"{side}Hand")]
        mid = pos[self.j(f"{side}HandMiddle1")]
        idx = pos[self.j(f"{side}HandIndex1")]
        pky = pos[self.j(f"{side}HandPinky1")]
        f = mid - h
        f /= np.linalg.norm(f)
        across = idx - pky                      # pinky -> index
        n = np.cross(f, across) if side == "Left" else np.cross(across, f)   # out of the palm
        n -= f * np.dot(n, f)
        return f, n / np.linalg.norm(n)

    def set_hand(self, pose, side, fingers, palm):
        """Turn the hand so the fingers point along `fingers` and the palm faces `palm`."""
        f0, n0 = self.hand_frame(pose, side)
        f1 = np.array(fingers, float); f1 /= np.linalg.norm(f1)
        n1 = np.array(palm, float); n1 -= f1 * np.dot(n1, f1); n1 /= np.linalg.norm(n1)
        A = np.stack([f0, n0, np.cross(f0, n0)], 1)
        B = np.stack([f1, n1, np.cross(f1, n1)], 1)
        r = R.from_matrix(B @ A.T)
        _, rot = self.fk(pose)
        self.set_world_rot(pose, f"{side}Hand", r * rot[self.j(f"{side}Hand")])

    def curl(self, pose, side, amount):
        """Curl the fingers (0 open, 1 fist) about each finger's own bend axis."""
        for fn in ("Index", "Middle", "Ring", "Pinky"):
            for k in (1, 2, 3):
                name = f"{side}Hand{fn}{k}"
                pos, rot = self.fk(pose)
                f, n = self.hand_frame(pose, side)
                axis = np.cross(f, n)          # turning +about f x n carries the tips toward the palm
                self.turn(pose, name, axis, amount * (55 if k == 1 else 70))
        for k in (2, 3):
            f, n = self.hand_frame(pose, side)
            self.turn(pose, f"{side}HandThumb{k}", n, 25 * amount * (1 if side == "Left" else -1))

#!/usr/bin/env python3
"""Camera rig simulator: fly a film camera move the way real gear can.

A drawn camera curve looks wrong when no real camera could fly it in the time
given, and a video model copies the layout's camera as is. This flies the move
with a simulated rig instead: a multirotor that moves only through stick
inputs (lean for acceleration, never past its tilt limit; drag sets top speed),
a gimbal operator who eases within rate limits, and a pilot's speed plan.

Engine-agnostic, Python 3.9+ standard library only. Coordinates are metres,
y up, heading 0 = looking along -z (Godot/OpenGL style). Pass --z-up on the
command line for Blender-style z-up files (x, y, z) -> converted in and out.

Rigs ("inspire3" limits are DJI's published Inspire 3 S-mode figures; the
others, the response times and the operator easing are approximate):
  inspire3  film drone: 26 m/s, 8 m/s climb/descent, 40 deg tilt, 150 deg/s
            yaw, gimbal 120 deg/s tilt and 270 deg/s pan
  fpv       chase drone: 33 m/s, 60 deg lean, light camera roll with the lean
  crane     crane arm or dolly: 3 m/s, about 1.2 m/s^2, slow gimbal
  handheld  operator on foot / Steadicam: 4 m/s, lag, seeded breathing drift

Command line:
  camera_rig.py fly  --rig crane --drawn drawn.csv --out flown.csv [--fps 30]
                     [--max-dev 0.5] [--max-aim 6] [--lead 0.2] [--z-up]
      drawn.csv columns: t,px,py,pz,lx,ly,lz  (lens position, look-at point)
      flown.csv columns: t,px,py,pz,lx,ly,lz,ux,uy,uz  (plus the up vector)
  camera_rig.py plan --rig inspire3 --path path.csv --dur 4.2 [--v0 3 --v1 3]
      path.csv columns: x,y,z (dense samples along the drawn path)
      prints the least time the path needs within the rig's comfortable
      limits, and whether it fits the story time.
  camera_rig.py selftest
"""

import argparse
import csv
import math
import sys

G = 9.81


# --- small vector helpers (tuples of 3 floats) -----------------------------

def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def length(a): return math.sqrt(dot(a, a))
def dist(a, b): return length(sub(a, b))


def norm(a):
    n = length(a)
    return (0.0, 0.0, 0.0) if n < 1e-9 else mul(a, 1.0 / n)


def limit(a, m):
    n = length(a)
    return a if n <= m or n < 1e-9 else mul(a, m / n)


def angle(a, b):
    na, nb = length(a), length(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return math.acos(max(-1.0, min(1.0, dot(a, b) / (na * nb))))


def slerp(a, b, w):
    a, b = norm(a), norm(b)
    om = angle(a, b)
    if om < 1e-6:
        return b
    s = math.sin(om)
    return norm(add(mul(a, math.sin((1 - w) * om) / s), mul(b, math.sin(w * om) / s)))


def rotate(v, axis, ang):
    k = norm(axis)
    c, s = math.cos(ang), math.sin(ang)
    return add(add(mul(v, c), mul(cross(k, v), s)), mul(k, dot(k, v) * (1 - c)))


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def move_toward(v, target, step):
    return target if abs(target - v) <= step else v + math.copysign(step, target - v)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


RIGS = {
    "inspire3": dict(vmax_h=26.0, vmax_up=8.0, vmax_down=8.0, tilt_max=40.0, yaw_rate_max=150.0,
                     gim_tilt_rate=120.0, gim_pan_rate=270.0, tilt_tau=0.15, tilt_rate=180.0,
                     vel_gain=1.5, vert_gain=2.5, vert_acc=6.0, gim_acc=300.0, gim_gain=4.0,
                     bank_gain=0.0, sway=0.0),
    "fpv": dict(vmax_h=33.0, vmax_up=15.0, vmax_down=15.0, tilt_max=60.0, yaw_rate_max=400.0,
                gim_tilt_rate=300.0, gim_pan_rate=400.0, tilt_tau=0.06, tilt_rate=600.0,
                vel_gain=3.0, vert_gain=4.0, vert_acc=14.0, gim_acc=900.0, gim_gain=8.0,
                bank_gain=0.15, sway=0.0),
    "crane": dict(vmax_h=3.0, vmax_up=1.5, vmax_down=1.5, tilt_max=7.0, yaw_rate_max=45.0,
                  gim_tilt_rate=40.0, gim_pan_rate=60.0, tilt_tau=0.15, tilt_rate=180.0,
                  vel_gain=0.9, vert_gain=1.2, vert_acc=0.8, gim_acc=60.0, gim_gain=2.0,
                  bank_gain=0.0, sway=0.0),
    "handheld": dict(vmax_h=4.0, vmax_up=1.0, vmax_down=1.0, tilt_max=17.0, yaw_rate_max=180.0,
                     gim_tilt_rate=90.0, gim_pan_rate=150.0, tilt_tau=0.15, tilt_rate=180.0,
                     vel_gain=2.0, vert_gain=2.5, vert_acc=6.0, gim_acc=200.0, gim_gain=3.0,
                     bank_gain=0.0, sway=0.04),
}

# Measured good leash per rig (metres the flown lens may stray from the drawn one).
DEFAULT_DEV = {"inspire3": 2.5, "fpv": 1.2, "crane": 0.5, "handheld": 0.35}


class Rig:
    """One camera rig. Drive it with fly_toward()+aim_at()+step(), or chase_drawn()."""

    def __init__(self, name="inspire3", seed=9):
        if name not in RIGS:
            raise ValueError("unknown rig %r (have %s)" % (name, ", ".join(RIGS)))
        self.name = name
        r = RIGS[name]
        rad = math.radians
        self.vmax_h, self.vmax_up, self.vmax_down = r["vmax_h"], r["vmax_up"], r["vmax_down"]
        self.tilt_max, self.yaw_rate_max = rad(r["tilt_max"]), rad(r["yaw_rate_max"])
        self.gim_tilt_rate, self.gim_pan_rate = rad(r["gim_tilt_rate"]), rad(r["gim_pan_rate"])
        self.tilt_tau, self.tilt_rate = r["tilt_tau"], rad(r["tilt_rate"])
        self.vel_gain, self.vert_gain, self.vert_acc = r["vel_gain"], r["vert_gain"], r["vert_acc"]
        self.gim_acc, self.gim_gain = rad(r["gim_acc"]), r["gim_gain"]
        self.bank_gain, self.sway = r["bank_gain"], r["sway"]
        self.gim_tilt_min, self.gim_tilt_max = rad(-89.0), rad(89.0)
        self.drag_k = G * math.tan(self.tilt_max) / (self.vmax_h ** 2)
        # Seeded smooth drift (sum of sines), so renders repeat.
        self._phase = [((seed * 7919 + i * 104729) % 1000) / 1000.0 * 2 * math.pi for i in range(9)]
        self._sway_t = 0.0
        self.start((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))

    # -- state --
    def start(self, pos, look_at):
        self.pos = tuple(pos)
        self.vel = (0.0, 0.0, 0.0)
        self.tilt = (0.0, 0.0)          # lean as (x, z) angles
        d = norm(sub(look_at, pos))
        self.pan = math.atan2(-d[0], -d[2])
        self.pitch = math.asin(clamp(d[1], -1.0, 1.0))
        self.yaw = self.pan
        self.yaw_vel = self.pan_vel = self.pitch_vel = 0.0
        self.sticks = (0.0, 0.0, 0.0, 0.0)
        self._drawn = (tuple(pos), tuple(look_at))

    def tilt_deg(self):
        return math.degrees(math.hypot(*self.tilt))

    def look_dir(self):
        cp = math.cos(self.pitch)
        return (-math.sin(self.pan) * cp, math.sin(self.pitch), -math.cos(self.pan) * cp)

    def lens_pos(self):
        if self.sway <= 0.0:
            return self.pos
        t, p = self._sway_t * 7.0, self._phase

        def n(i):
            return (math.sin(t * 0.31 + p[i]) + 0.6 * math.sin(t * 0.73 + p[i + 3]) + 0.3 * math.sin(t * 1.37 + p[i + 6])) / 1.9
        return add(self.pos, mul((n(0), n(1) * 0.6, n(2)), self.sway * 2.0))

    def cam_up(self):
        if self.bank_gain <= 0.0 or math.hypot(*self.tilt) < 1e-4:
            return (0.0, 1.0, 0.0)
        fwd = self.look_dir()
        side = norm(cross(fwd, (0.0, 1.0, 0.0)))
        roll = -dot((self.tilt[0], 0.0, self.tilt[1]), side) * self.bank_gain
        return rotate((0.0, 1.0, 0.0), fwd, roll)

    # -- pilot and operator --
    def set_sticks(self, roll, pitch_fwd, throttle, yaw_s):
        self.sticks = tuple(clamp(v, -1.0, 1.0) for v in (roll, pitch_fwd, throttle, yaw_s))

    def fly_toward(self, target, target_vel, gap_gain=1.2):
        want = add(target_vel, mul(sub(target, self.pos), gap_gain))
        fwd = (-math.sin(self.yaw), 0.0, -math.cos(self.yaw))
        right = (math.cos(self.yaw), 0.0, -math.sin(self.yaw))
        hx, hy = dot(want, right) / self.vmax_h, dot(want, fwd) / self.vmax_h
        hn = math.hypot(hx, hy)
        if hn > 1.0:
            hx, hy = hx / hn, hy / hn
        thr = want[1] / (self.vmax_up if want[1] > 0 else self.vmax_down)
        dy = wrap(self.pan - self.yaw)
        self.set_sticks(hx, hy, thr, dy * 2.0 / self.yaw_rate_max)

    def aim_at(self, target, dt):
        d = norm(sub(target, self.pos))
        want_pan = math.atan2(-d[0], -d[2])
        want_pitch = clamp(math.asin(clamp(d[1], -1.0, 1.0)), self.gim_tilt_min, self.gim_tilt_max)
        rp = clamp(wrap(want_pan - self.pan) * self.gim_gain, -self.gim_pan_rate, self.gim_pan_rate)
        rt = clamp((want_pitch - self.pitch) * self.gim_gain, -self.gim_tilt_rate, self.gim_tilt_rate)
        self.pan_vel = move_toward(self.pan_vel, rp, self.gim_acc * dt)
        self.pitch_vel = move_toward(self.pitch_vel, rt, self.gim_acc * dt)
        self.pan = wrap(self.pan + self.pan_vel * dt)
        self.pitch = clamp(self.pitch + self.pitch_vel * dt, self.gim_tilt_min, self.gim_tilt_max)

    def step(self, dt):
        """Advance by dt (keep dt at 1/240 s or less)."""
        sx, sy, sz, sw = self.sticks
        fwd = (-math.sin(self.yaw), 0.0, -math.cos(self.yaw))
        right = (math.cos(self.yaw), 0.0, -math.sin(self.yaw))
        v_cmd = limit(add(mul(right, sx * self.vmax_h), mul(fwd, sy * self.vmax_h)), self.vmax_h)
        vh = (self.vel[0], 0.0, self.vel[2])
        a_need = add(mul(sub(v_cmd, vh), self.vel_gain), mul(vh, length(vh) * self.drag_k))
        an = length(a_need)
        lean = min(math.atan(an / G), self.tilt_max)
        t_des = (a_need[0] / an * lean, a_need[2] / an * lean) if an > 1e-4 else (0.0, 0.0)
        k = min(1.0, dt / self.tilt_tau)
        ts = ((t_des[0] - self.tilt[0]) * k, (t_des[1] - self.tilt[1]) * k)
        tsn = math.hypot(*ts)
        if tsn > self.tilt_rate * dt:
            ts = (ts[0] / tsn * self.tilt_rate * dt, ts[1] / tsn * self.tilt_rate * dt)
        tx, tz = self.tilt[0] + ts[0], self.tilt[1] + ts[1]
        tn = math.hypot(tx, tz)
        if tn > self.tilt_max:
            tx, tz = tx / tn * self.tilt_max, tz / tn * self.tilt_max
            tn = self.tilt_max
        self.tilt = (tx, tz)
        a_h = (0.0, 0.0, 0.0)
        if tn > 1e-4:
            a_h = mul((tx / tn, 0.0, tz / tn), G * math.tan(tn))
        a_h = sub(a_h, mul(vh, length(vh) * self.drag_k))
        vy_cmd = sz * (self.vmax_up if sz > 0 else self.vmax_down)
        a_y = clamp((vy_cmd - self.vel[1]) * self.vert_gain, -self.vert_acc, self.vert_acc)
        self.vel = add(self.vel, mul((a_h[0], a_y, a_h[2]), dt))
        self.pos = add(self.pos, mul(self.vel, dt))
        self.yaw_vel = move_toward(self.yaw_vel, sw * self.yaw_rate_max, math.radians(400.0) * dt)
        self.yaw = wrap(self.yaw + self.yaw_vel * dt)
        self._sway_t += dt

    def chase_drawn(self, drawn_pos, drawn_look, dt, lead=0.2, max_dev=None, max_aim=6.0):
        """Fly one frame of an existing drawn camera, held on two leashes.

        The drawn move is the pilot's mark, chased `lead` s ahead. The lens stays
        within max_dev metres of the drawn lens; the aim lags the drawn aim by at
        most max_aim degrees. A drawn jump (a cut) restarts the rig on its mark.
        Returns (lens, look_point, up)."""
        if max_dev is None:
            max_dev = DEFAULT_DEV.get(self.name, 1.0)
        last_pos, last_look = self._drawn
        if dist(last_pos, drawn_pos) > max(3.0, 60.0 * dt):
            self.start(drawn_pos, drawn_look)
            return tuple(drawn_pos), tuple(drawn_look), (0.0, 1.0, 0.0)
        v_draw = mul(sub(drawn_pos, last_pos), 1.0 / max(dt, 1e-4))
        l_draw = mul(sub(drawn_look, last_look), 1.0 / max(dt, 1e-4))
        self._drawn = (tuple(drawn_pos), tuple(drawn_look))
        target = add(drawn_pos, mul(v_draw, lead))
        aim = add(drawn_look, mul(l_draw, lead))
        steps = max(1, round(dt * 240.0))
        h = dt / steps
        for _ in range(steps):
            self.fly_toward(target, v_draw)
            self.aim_at(aim, h)
            self.step(h)
        off = sub(self.pos, drawn_pos)
        if length(off) > max_dev:
            self.pos = add(drawn_pos, limit(off, max_dev))
        lens = self.lens_pos()
        gd = self.look_dir()
        want = norm(sub(aim, lens))
        ang = angle(gd, want)
        amax = math.radians(max_aim)
        if ang > amax:
            gd = slerp(gd, want, 1.0 - amax / ang)
        return lens, add(lens, mul(gd, 10.0)), self.cam_up()

    def plan_limits(self, margin=0.7):
        """Comfortable pilot limits for plan_speeds() (a fraction of the hard ones)."""
        a = G * math.tan(self.tilt_max) * margin
        return {"vmax": self.vmax_h * margin, "a_along": a, "a_lat": a * 0.9,
                "v_vert": min(self.vmax_up, self.vmax_down) * margin}


def plan_speeds(pts, dur, v0, v1, limits):
    """A pilot's speed plan along dense path samples, searched to take `dur` s.

    Limits along-path acceleration, cornering, climb/descent and top speed;
    starts at v0 and ends at v1 so legs join at matching speeds.
    Returns dict(times, dist, top, total, fits)."""
    n = len(pts)
    cum = [0.0]
    for k in range(1, n):
        cum.append(cum[-1] + dist(pts[k], pts[k - 1]))
    vmax, a_along = limits.get("vmax", 18.0), limits.get("a_along", 5.5)
    a_lat, v_vert = limits.get("a_lat", 5.0), limits.get("v_vert", 7.0)
    lim = []
    for k in range(n):
        a, b, c = pts[max(k - 6, 0)], pts[k], pts[min(k + 6, n - 1)]
        d1, d2 = sub(b, a), sub(c, b)
        curv = 0.0
        if length(d1) > 0.01 and length(d2) > 0.01:
            curv = angle(d1, d2) / max(0.01, 0.5 * (length(d1) + length(d2)))
        dy = norm(sub(c, a))[1]
        v = vmax
        if curv > 1e-4:
            v = min(v, math.sqrt(a_lat / curv))
        if abs(dy) > 0.01:
            v = min(v, v_vert / abs(dy))
        lim.append(v)
    lo, hi, best = 0.3, vmax, None
    for _ in range(40):
        vc = 0.5 * (lo + hi)
        vs = [min(l, vc) for l in lim]
        vs[0] = min(vs[0], v0)
        for k in range(1, n):
            vs[k] = min(vs[k], math.sqrt(vs[k - 1] ** 2 + 2 * a_along * (cum[k] - cum[k - 1])))
        vs[-1] = min(vs[-1], v1)
        for k in range(n - 2, -1, -1):
            vs[k] = min(vs[k], math.sqrt(vs[k + 1] ** 2 + 2 * a_along * (cum[k + 1] - cum[k])))
        ts = [0.0]
        for k in range(1, n):
            ts.append(ts[-1] + (cum[k] - cum[k - 1]) / max(0.05, 0.5 * (vs[k] + vs[k - 1])))
        best = {"times": ts, "dist": cum, "top": max(vs), "total": ts[-1]}
        if ts[-1] > dur:
            lo = vc
        else:
            hi = vc
    best["fits"] = best["total"] <= dur * 1.02
    return best


def min_duration(pts, v0, v1, limits):
    """The least time the path can be flown in within the limits."""
    return plan_speeds(pts, 0.0, v0, v1, limits)["total"]


def guard_lens(raycast, lens, look, prev_frac=1.0, max_dist=14.0, ease_out=0.08):
    """Keep a close camera out of walls and roofs.

    raycast(a, b) returns the first hit point on the SET between a and b, or
    None (skip characters, so a body crossing the lens doesn't yank it). When
    the set is in the way the lens comes in in front of it at once, then eases
    back out over later frames. Keep prev_frac per shot (start at 1.0).
    Returns (lens, frac)."""
    to_cam = sub(lens, look)
    d = length(to_cam)
    if d < 0.5 or d > max_dist:
        return tuple(lens), 1.0
    u = mul(to_cam, 1.0 / d)
    frac = 1.0
    hit = raycast(add(look, mul(u, 0.3)), add(lens, mul(u, 0.4)))
    if hit is not None:
        frac = clamp(dist(hit, look) / d - 0.5 / d, 0.15, 1.0)
    frac = min(frac, prev_frac + (1.0 - prev_frac) * ease_out)
    return add(look, mul(to_cam, frac)), frac


# --- command line -----------------------------------------------------------

def _io(v, z_up, inbound):
    """Blender z-up (x, y, z) <-> internal y-up (x, z, -y)."""
    if not z_up:
        return tuple(v)
    return (v[0], v[2], -v[1]) if inbound else (v[0], -v[2], v[1])


def _read(path):
    with open(path, newline="") as f:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(f)]


def cmd_fly(a):
    rows = _read(a.drawn)
    rig = Rig(a.rig)
    out = []
    prev_t = None
    for r in rows:
        p = _io((r["px"], r["py"], r["pz"]), a.z_up, True)
        l = _io((r["lx"], r["ly"], r["lz"]), a.z_up, True)
        dt = (r["t"] - prev_t) if prev_t is not None else 1.0 / a.fps
        prev_t = r["t"]
        if not out:
            rig.start(p, l)
            lens, look, up = p, l, (0.0, 1.0, 0.0)
        else:
            lens, look, up = rig.chase_drawn(p, l, dt, a.lead, a.max_dev, a.max_aim)
        out.append([r["t"], *_io(lens, a.z_up, False), *_io(look, a.z_up, False), *_io(up, a.z_up, False)])
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "px", "py", "pz", "lx", "ly", "lz", "ux", "uy", "uz"])
        for row in out:
            w.writerow(["%.4f" % row[0]] + ["%.4f" % v for v in row[1:]])
    print("flew %d frames with %s -> %s" % (len(out), a.rig, a.out))


def cmd_plan(a):
    pts = [_io((r["x"], r["y"], r["z"]), a.z_up, True) for r in _read(a.path)]
    lim = Rig(a.rig).plan_limits(a.margin)
    need = min_duration(pts, a.v0, a.v1, lim)
    plan = plan_speeds(pts, a.dur, a.v0, a.v1, lim)
    print("path %.1f m; least time within %s limits (margin %.2f): %.2f s; story gives %.2f s -> %s"
          % (plan["dist"][-1], a.rig, a.margin, need, a.dur,
             "fits (top %.1f m/s)" % plan["top"] if plan["fits"] else "DOES NOT FIT: hold the story or shorten the move"))
    return 0 if plan["fits"] else 2


def selftest():
    fails = []

    def check(label, ok):
        print(("ok    " if ok else "FAIL  ") + label)
        if not ok:
            fails.append(label)

    h = 1.0 / 240.0
    for name in RIGS:
        r = Rig(name)
        r.start((0, 0, 0), (0, 0, -10))
        vtop = ltop = 0.0
        t = 0.0
        while t < 8.0:
            goal = (0.0, 2.0, -min(200.0, 40.0 * t))
            r.fly_toward(goal, (0.0, 0.0, -40.0))
            r.aim_at(add(goal, (0, 0, -10)), h)
            r.step(h)
            vtop = max(vtop, math.hypot(r.vel[0], r.vel[2]))
            ltop = max(ltop, r.tilt_deg())
            t += h
        check("%s top speed %.1f <= %.1f m/s" % (name, vtop, r.vmax_h), vtop <= r.vmax_h * 1.01)
        check("%s lean %.1f <= %.1f deg" % (name, ltop, math.degrees(r.tilt_max)), ltop <= math.degrees(r.tilt_max) + 0.01)
    f = Rig("fpv")
    f.start((0, 0, 0), (0, 0, -10))
    roll_top, t = 0.0, 0.0
    while t < 3.0:
        goal = (30.0 * math.sin(t * 2.0), 0.0, -20.0 * t)
        f.fly_toward(goal, (60.0 * math.cos(t * 2.0), 0.0, -20.0))
        f.aim_at(add(goal, (0, 0, -10)), h)
        f.step(h)
        roll_top = max(roll_top, math.degrees(angle(f.cam_up(), (0, 1, 0))))
        t += h
    check("fpv camera roll %.1f deg stays under 10" % roll_top, roll_top < 10.0)
    a, b = Rig("handheld"), Rig("handheld")
    for _ in range(480):
        a.step(h)
        b.step(h)
    check("handheld drift repeats and moves the lens", a.lens_pos() == b.lens_pos() and a.lens_pos() != a.pos)
    pts = []
    for i in range(401):
        k = i / 400.0
        pts.append((-30.0 * math.sin(k * math.pi * 0.5), 40.0 - 33.0 * k * k, -70.0 * k))
    lim = Rig("inspire3").plan_limits(0.7)
    need = min_duration(pts, 3.0, 3.0, lim)
    check("82 m reveal with a 33 m drop needs %.1f s, far more than 4.2" % need, need > 6.3)
    check("a 4.2 s slot does not fit", not plan_speeds(pts, 4.2, 3.0, 3.0, lim)["fits"])
    roomy = plan_speeds(pts, need + 3.0, 3.0, 3.0, lim)
    check("a %.1f s slot fits and is used (%.2f s)" % (need + 3.0, roomy["total"]),
          roomy["fits"] and abs(roomy["total"] - (need + 3.0)) < 0.1)
    c = Rig("crane")
    c.start((0, 0, 0), (0, 0, -10))
    dev_top = aim_top = 0.0
    dt = 1.0 / 30.0
    prev_dl = (0.0, 0.0, -10.0)
    for i in range(60):
        dp = (0.0, 0.0, -0.5 * i)
        dl = add(dp, (5.0 * math.sin(i * 0.3), 0.0, -10.0))
        lens, look, _ = c.chase_drawn(dp, dl, dt, 0.2, 0.5, 6.0)
        dev_top = max(dev_top, dist(lens, dp))
        aim = add(dl, mul(sub(dl, prev_dl), 0.2 / dt))
        prev_dl = dl
        aim_top = max(aim_top, math.degrees(angle(sub(look, lens), sub(aim, lens))))
    check("crane leash: lens within %.2f m of the drawn lens (<= 0.5)" % dev_top, dev_top <= 0.501)
    check("crane leash: aim within %.1f deg of the drawn aim (<= 6)" % aim_top, aim_top <= 6.01)
    lens, _, _ = c.chase_drawn((100.0, 5.0, 0.0), (100.0, 5.0, -10.0), dt)
    check("a drawn cut restarts the rig on its mark", lens == (100.0, 5.0, 0.0))
    wall = lambda p, q: (0.0, 0.0, 2.0) if p[2] < 2.0 < q[2] else None
    g, frac = guard_lens(wall, (0.0, 0.0, 5.0), (0.0, 0.0, 0.0))
    check("guard pulls the lens in front of a wall (z %.2f < 2)" % g[2], g[2] < 2.0 and frac < 1.0)
    g2, frac2 = guard_lens(lambda p, q: None, (0.0, 0.0, 5.0), (0.0, 0.0, 0.0), frac)
    check("guard eases back out, not at once (frac %.2f -> %.2f)" % (frac, frac2), frac < frac2 < 1.0)
    print("camera_rig selftest: %s" % ("PASS" if not fails else "%d FAILED" % len(fails)))
    return 1 if fails else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    fl = sp.add_parser("fly", help="fly a drawn camera with a rig")
    fl.add_argument("--rig", default="inspire3", choices=sorted(RIGS))
    fl.add_argument("--drawn", required=True)
    fl.add_argument("--out", required=True)
    fl.add_argument("--fps", type=float, default=30.0)
    fl.add_argument("--lead", type=float, default=0.2)
    fl.add_argument("--max-dev", type=float, default=None)
    fl.add_argument("--max-aim", type=float, default=6.0)
    fl.add_argument("--z-up", action="store_true")
    pl = sp.add_parser("plan", help="check a path against the story time")
    pl.add_argument("--rig", default="inspire3", choices=sorted(RIGS))
    pl.add_argument("--path", required=True)
    pl.add_argument("--dur", type=float, required=True)
    pl.add_argument("--v0", type=float, default=0.0)
    pl.add_argument("--v1", type=float, default=0.0)
    pl.add_argument("--margin", type=float, default=0.7)
    pl.add_argument("--z-up", action="store_true")
    sp.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "fly":
        cmd_fly(a)
        return 0
    if a.cmd == "plan":
        return cmd_plan(a)
    return selftest()


if __name__ == "__main__":
    sys.exit(main())

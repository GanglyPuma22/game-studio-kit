"""Shared by the speech and voice-casting recipes (packed next to each
recipe's worker.py). Never needs credentials: the weights are public and
pinned file by file in recipe.json.

    fetch(recipe, dest)   download each pinned file at the pinned revision,
                          check its SHA-256 (large files) or git blob id
                          (small files), then turn the hub offline so no
                          library downloads anything else behind our back
    Session(...)          the generation loop: one model load, one take per
                          cue and seed, the plan's repeats after a reload,
                          float originals, level-matched previews and a
                          receipt.json rewritten after every take

A take longer than its max_seconds is kept whole and flagged (never cut).
Nothing here decides whether a take is good: that needs a person listening.
"""
import gc
import hashlib
import json
import os
import random
import sys
import time
import traceback
import urllib.request
from pathlib import Path

HUB = "https://huggingface.co"
PREVIEW_RMS_DB = -20.0   # previews sit at the same loudness so takes compare fairly
PREVIEW_PEAK_DB = -1.0   # ...unless that would push a peak past -1 dBFS


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def git_oid(path):
    """Git's blob id (what the hub lists for files kept outside LFS)."""
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def matches(path, pin):
    if not Path(path).is_file() or Path(path).stat().st_size != pin["size"]:
        return False
    return sha256(path) == pin["sha256"] if "sha256" in pin else git_oid(path) == pin["git_oid"]


def fetch(recipe, dest):
    """Every file the recipe pins, at its revision, checked. Returns seconds taken."""
    m = recipe["model"]
    t0 = time.time()
    for part in [m] + list(m.get("also", [])):
        root = Path(dest) / part.get("subdir", "")
        for rel, pin in part["files"].items():
            out = root / rel
            if matches(out, pin):
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            url = f"{HUB}/{part['repo']}/resolve/{part['revision']}/{urllib.request.quote(rel)}"
            tmp = out.with_suffix(out.suffix + ".part")
            with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as w:
                for b in iter(lambda: r.read(1 << 20), b""):
                    w.write(b)
            tmp.replace(out)
            if not matches(out, pin):
                raise RuntimeError(f"{part['repo']}/{rel} does not match its pin")
    # From here on, a library that tries to download is refused instead.
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1")
    return round(time.time() - t0, 1)


def _torch():
    try:
        import torch
        return torch
    except ImportError:  # offline tests of the loop itself
        return None


def seed_all(seed):
    import numpy as np

    random.seed(seed)
    np.random.seed(seed % 2**32)
    torch = _torch()
    if torch is not None:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)


def _cuda():
    torch = _torch()
    return torch if torch is not None and torch.cuda.is_available() else None


def merged_controls(plan, cue):
    return {**(plan.get("controls") or {}), **(cue.get("controls") or {})}


class Session:
    """load() -> model; take(model, cue, seed, controls, ref) -> (float array
    (frames,) or (frames, channels), sample rate). ref is {path, transcript,
    sha256} for speech, None for casting."""

    def __init__(self, recipe_dir, plan_path, model_dir, out_dir, inputs_dir=None):
        self.recipe_dir = Path(recipe_dir)
        self.recipe = json.loads((self.recipe_dir / "recipe.json").read_text())
        # Packed copies sit in a folder named repo/: the packer writes the real name beside them.
        named = self.recipe_dir / "recipe.name"
        self.name = named.read_text().strip() if named.is_file() else self.recipe_dir.name
        self.plan = json.loads(Path(plan_path).read_text())
        self.model_dir = Path(model_dir)
        self.out = Path(out_dir)
        self.inputs = Path(inputs_dir) if inputs_dir else None
        (self.out / "originals").mkdir(parents=True, exist_ok=True)
        (self.out / "previews").mkdir(exist_ok=True)
        m = self.recipe["model"]
        job = Path(os.environ.get("JOB_ROOT", "/content/job"))
        self.receipt = {
            "recipe": self.name, "kind": self.recipe["kind"], "experimental": self.recipe.get("experimental", False),
            "status": "running", "listening_review": "not_run",
            "kit_commit": (job / "commit.txt").read_text().strip() if (job / "commit.txt").is_file() else os.environ.get("STUDIO_COMMIT", "unknown"),
            "engine": {"source": m.get("source"), "commit": m.get("commit")},
            "model": [{"repo": p["repo"], "revision": p["revision"]} for p in [m] + list(m.get("also", []))],
            "license": m.get("license"), "output_terms": self.recipe.get("output_terms"),
            "character": self.plan.get("character"), "language": self.plan.get("language"),
            "plan": {k: v for k, v in self.plan.items() if k != "reference"},
            "reference": None, "outputs": [],
        }
        self.private = set()
        self.ref = None

    def save(self):
        (self.out / "receipt.json").write_text(json.dumps(self.receipt, indent=2, default=str))

    def _reference(self):
        ref = self.plan.get("reference")
        if not ref:
            return None
        path = (self.inputs / ref["input"]).resolve()
        if self.inputs.resolve() not in path.parents or sha256(path) != ref["sha256"]:
            raise RuntimeError("the reference voice is missing or does not match its sha256")
        self.private.add(ref["sha256"])
        # The receipt names the reference by hash only: the file never leaves the runtime.
        self.receipt["reference"] = {"input": ref["input"], "sha256": ref["sha256"], "transcript": ref["transcript"]}
        return {"path": str(path), "transcript": ref["transcript"], "sha256": ref["sha256"]}

    def _write(self, cue, seed, x, rate, gen_seconds, repeat_of=None):
        import numpy as np
        import soundfile as sf

        x = np.asarray(x, dtype=np.float32)
        if x.ndim == 1:
            x = x[:, None]
        name = f"{cue['id']}-{seed}" + ("-repeat" if repeat_of else "")
        if not np.isfinite(x).all():
            raise RuntimeError(f"{name}: not finite")
        rms = float(np.sqrt(np.mean(x * x)))
        if rms < 1e-5:
            raise RuntimeError(f"{name}: silent")
        peak = float(np.max(np.abs(x)))
        orig = self.out / "originals" / f"{name}.wav"
        sf.write(orig, x, rate, subtype="FLOAT")
        gain = min(10 ** (PREVIEW_RMS_DB / 20) / rms, 10 ** (PREVIEW_PEAK_DB / 20) / max(peak, 1e-9))
        prev = self.out / "previews" / f"{name}.wav"
        sf.write(prev, np.clip(x * gain, -1, 1), rate, subtype="PCM_16")
        if {sha256(orig), sha256(prev)} & self.private:
            orig.unlink()
            prev.unlink()
            raise RuntimeError(f"{name}: an output is a copy of a private input (deleted)")
        secs = x.shape[0] / rate
        limit = float(cue.get("max_seconds", self.plan.get("max_seconds")))
        entry = {
            "cue": cue["id"], "line_id": cue.get("line_id"), "text": cue["text"], "delivery": cue.get("delivery"),
            "seed": seed, "controls": merged_controls(self.plan, cue), "generate_seconds": round(gen_seconds, 2),
            "peak_vram_bytes": _cuda().max_memory_allocated() if _cuda() else None,
            "seconds": round(secs, 3), "max_seconds": limit, "overlength": secs > limit,
            "original": {"path": str(orig.relative_to(self.out)), "sha256": sha256(orig), "sample_rate": rate,
                         "channels": x.shape[1], "frames": x.shape[0], "peak": peak, "rms": rms},
            "preview": {"path": str(prev.relative_to(self.out)), "sha256": sha256(prev), "gain": gain,
                        "format": "PCM_16", "level": f"RMS {PREVIEW_RMS_DB} dBFS, peak at most {PREVIEW_PEAK_DB} dBFS"},
        }
        if repeat_of:
            first = repeat_of["original"]
            entry["repeat_of"] = f"{cue['id']}-{seed}"
            entry["after_reload"] = True
            entry["same_bytes"] = entry["original"]["sha256"] == first["sha256"]
            entry["same_frames"] = entry["original"]["frames"] == first["frames"]
        self.receipt["outputs"].append(entry)
        self.save()
        print("DONE", name, f"{gen_seconds:.1f}s", "OVERLENGTH" if entry["overlength"] else "", flush=True)
        return entry

    def run(self, load, take):
        try:
            self.receipt["download_seconds"] = fetch(self.recipe, self.model_dir)
            cuda = _cuda()
            if cuda:
                self.receipt["hardware"] = {"gpu": cuda.cuda.get_device_name(0), "torch": cuda.__version__}
            self.ref = self._reference()
            t = time.perf_counter()
            model = load(self.model_dir)
            self.receipt["load_seconds"] = round(time.perf_counter() - t, 2)
            self.save()
            cues = {c["id"]: c for c in self.plan["cues"]}
            first = {}
            for cue in self.plan["cues"]:
                for seed in cue["seeds"]:
                    first[(cue["id"], seed)] = self._take(model, take, cue, seed)
            repeats = self.plan.get("repeats", [])
            if repeats:
                # Same cue, same seed, a freshly loaded model: does the engine give the same take back?
                del model
                gc.collect()
                if _cuda():
                    _cuda().cuda.empty_cache()
                model = load(self.model_dir)
                for r in repeats:
                    self._take(model, take, cues[r["cue"]], r["seed"], first[(r["cue"], r["seed"])])
            want = sum(len(c["seeds"]) for c in self.plan["cues"]) + len(repeats)
            if len(self.receipt["outputs"]) != want:
                raise RuntimeError(f"{len(self.receipt['outputs'])} outputs, expected {want}")
            self.receipt["status"] = "generated_pending_listening"
        except BaseException:
            self.receipt["status"] = "failed"
            self.receipt["traceback"] = traceback.format_exc()
            print(self.receipt["traceback"], flush=True)
            self.save()
            sys.exit(1)
        self.save()

    def _take(self, model, take, cue, seed, repeat_of=None):
        if _cuda():
            _cuda().cuda.reset_peak_memory_stats()
        seed_all(seed)
        t = time.perf_counter()
        x, rate = take(model, cue, seed, merged_controls(self.plan, cue), self.ref)
        return self._write(cue, seed, x, rate, time.perf_counter() - t, repeat_of)

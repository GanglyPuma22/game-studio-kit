"""Stable Audio Open worker: one pipeline load, one call per cue and seed.
Writes originals/<cue>-<seed>.wav (float, untouched), previews/<cue>-<seed>.wav
(PCM16, peak -1 dBFS) and receipt.json (per file: hash, rate, channels, frames,
peak, RMS, seconds to generate). Fails if any output is missing, silent or not
finite. The receipt records files, not whether they fit their prompt: that
needs a person listening."""
import hashlib, json, sys, time, traceback
from pathlib import Path

plan_path, model_dir, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
plan = json.loads(plan_path.read_text())
(out / "originals").mkdir(parents=True, exist_ok=True)
(out / "previews").mkdir(exist_ok=True)
receipt = {"recipe": "stable-audio-open-sfx", "plan": plan, "status": "running", "outputs": [],
           "listening_review": "not_run"}


def save():
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


try:
    import numpy as np
    import soundfile as sf
    import torch
    from diffusers import StableAudioPipeline

    t0 = time.perf_counter()
    pipe = StableAudioPipeline.from_pretrained(model_dir, torch_dtype=torch.float16).to("cuda")
    rate = pipe.vae.sampling_rate
    receipt["load_seconds"] = round(time.perf_counter() - t0, 2)
    receipt["hardware"] = {"gpu": torch.cuda.get_device_name(0), "torch": torch.__version__}
    steps = int(plan.get("steps", 100))
    guidance = float(plan.get("guidance", 7.0))
    for cue in plan["cues"]:
        secs = float(cue.get("seconds", plan.get("seconds", 5)))
        neg = cue.get("negative_prompt", plan.get("negative_prompt"))
        for seed in cue["seeds"]:
            name = f"{cue['id']}-{seed}"
            t = time.perf_counter()
            torch.cuda.reset_peak_memory_stats()
            g = torch.Generator("cuda").manual_seed(seed)
            audio = pipe(cue["prompt"], negative_prompt=neg, num_inference_steps=steps, guidance_scale=guidance,
                         audio_end_in_s=secs, num_waveforms_per_prompt=1, generator=g).audios[0]
            x = audio.T.float().cpu().numpy()  # (frames, channels)
            gen = time.perf_counter() - t
            if not np.isfinite(x).all():
                raise RuntimeError(f"{name}: not finite")
            rms = float(np.sqrt(np.mean(x * x)))
            if rms < 1e-5:
                raise RuntimeError(f"{name}: silent")
            orig = out / "originals" / f"{name}.wav"
            sf.write(orig, x, rate, subtype="FLOAT")
            peak = float(np.max(np.abs(x)))
            gain = (10 ** (-1 / 20)) / max(peak, 1e-9)
            prev = out / "previews" / f"{name}.wav"
            sf.write(prev, np.clip(x * gain, -1, 1), rate, subtype="PCM_16")
            receipt["outputs"].append({
                "cue": cue["id"], "seed": seed, "prompt": cue["prompt"], "negative_prompt": neg,
                "seconds_requested": secs, "steps": steps, "guidance": guidance,
                "generate_seconds": round(gen, 2), "peak_vram_bytes": torch.cuda.max_memory_allocated(),
                "original": {"path": str(orig.relative_to(out)), "sha256": sha(orig), "sample_rate": rate,
                             "channels": x.shape[1], "frames": x.shape[0], "peak": peak, "rms": rms},
                "preview": {"path": str(prev.relative_to(out)), "sha256": sha(prev), "gain": gain, "format": "PCM_16"},
            })
            save()
            print("DONE", name, f"{gen:.1f}s", flush=True)
    want = sum(len(c["seeds"]) for c in plan["cues"])
    if len(receipt["outputs"]) != want:
        raise RuntimeError(f"{len(receipt['outputs'])} outputs, expected {want}")
    receipt["status"] = "generated_pending_listening"
except BaseException:
    receipt["status"] = "failed"
    receipt["traceback"] = traceback.format_exc()
    print(receipt["traceback"], flush=True)
    save()
    sys.exit(1)
save()

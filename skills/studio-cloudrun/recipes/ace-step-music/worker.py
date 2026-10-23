"""ACE-Step 1.5 worker (run inside the upstream uv environment). Downloads the
pinned model revisions, loads the audio model and planner once, then makes one
track per cue and seed. Writes originals/<cue>-<seed>/*.flac (untouched),
optional loops/<cue>-<seed>.wav (overlap crossfade, PCM16) with a wrap audition
in seams/, and receipt.json after every track. Never retries a track. A loop
file is a candidate: whether the seam sounds right needs a person listening."""
import hashlib, json, subprocess, sys, time, traceback
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text())
recipe = json.loads(Path(sys.argv[2]).read_text())
out = Path(sys.argv[3])
repo = Path.cwd()
out.mkdir(parents=True, exist_ok=True)
receipt = {"recipe": "ace-step-music", "plan": plan, "status": "running", "outputs": [],
           "listening_review": "not_run", "loop_seam_review": "not_run"}


def save():
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, default=str))


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
    from huggingface_hub import snapshot_download
    from acestep.handler import AceStepHandler
    from acestep.llm_inference import LLMHandler
    from acestep.inference import GenerationParams, GenerationConfig, generate_music

    gpu = torch.cuda.get_device_properties(0)
    receipt["hardware"] = {"gpu": gpu.name, "vram_bytes": gpu.total_memory, "torch": torch.__version__}
    receipt["upstream_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if receipt["upstream_commit"] != recipe["model"]["commit"]:
        raise RuntimeError("upstream checkout is not the pinned commit")
    revs = recipe["model"]["repos"]
    dit_name, lm_name = plan.get("dit_model", "acestep-v15-xl-sft"), plan.get("lm_model", "acestep-5Hz-lm-4B")
    ck = repo / "checkpoints"
    t = time.perf_counter()
    for rid, dest in [("ACE-Step/Ace-Step1.5", ck), (f"ACE-Step/{dit_name}", ck / dit_name), (f"ACE-Step/{lm_name}", ck / lm_name)]:
        if rid not in revs:
            raise RuntimeError(f"{rid} has no pinned revision in recipe.json")
        snapshot_download(rid, revision=revs[rid], local_dir=dest, max_workers=8)
    receipt["model_revisions"] = revs
    receipt["download_seconds"] = round(time.perf_counter() - t, 1)
    save()
    t = time.perf_counter()
    dit = AceStepHandler()
    status, ok = dit.initialize_service(project_root=str(repo), config_path=dit_name, device="cuda",
                                        compile_model=False, offload_to_cpu=False, quantization=None)
    if not ok:
        raise RuntimeError(status)
    lm = LLMHandler()
    status, ok = lm.initialize(checkpoint_dir=str(ck), lm_model_path=lm_name, backend=plan.get("lm_backend", "vllm"),
                               device="cuda", offload_to_cpu=False, dtype=torch.bfloat16)
    if not ok:
        raise RuntimeError(status)
    receipt["actual_lm_backend"] = lm.llm_backend
    receipt["load_seconds"] = round(time.perf_counter() - t, 1)
    save()
    fade = float(plan.get("loop_crossfade_seconds", 0))
    for cue in plan["cues"]:
        secs = float(cue.get("seconds", plan.get("seconds", 180)))
        for seed in cue["seeds"]:
            name = f"{cue['id']}-{seed}"
            t = time.perf_counter()
            torch.cuda.reset_peak_memory_stats()
            params = GenerationParams(
                task_type="text2music", caption=cue["caption"], lyrics="[Instrumental]", instrumental=True,
                vocal_language="unknown", bpm=cue.get("bpm"), keyscale=cue.get("keyscale", ""),
                timesignature=str(cue.get("time_signature", "4")), duration=secs,
                inference_steps=int(plan.get("inference_steps", 50)), guidance_scale=float(plan.get("guidance_scale", 7.0)),
                shift=1.0, seed=seed, thinking=True, use_cot_metas=True, use_cot_caption=False, use_cot_lyrics=False,
                lm_temperature=0.85, lm_cfg_scale=2.0)
            config = GenerationConfig(batch_size=1, allow_lm_batch=False, use_random_seed=False, seeds=[seed], audio_format="flac")
            result = generate_music(dit, lm, params, config, save_dir=str(out / "originals" / name))
            torch.cuda.synchronize()
            entry = {"cue": cue["id"], "seed": seed, "caption": cue["caption"], "bpm": cue.get("bpm"),
                     "keyscale": cue.get("keyscale"), "seconds_requested": secs,
                     "generate_seconds": round(time.perf_counter() - t, 2), "success": result.success,
                     "error": result.error, "peak_vram_bytes": torch.cuda.max_memory_allocated()}
            receipt["outputs"].append(entry)
            save()
            if not result.success or len(result.audios) != 1:
                raise RuntimeError(f"{name}: {result.error}")
            orig = Path(result.audios[0]["path"])
            x, sr = sf.read(orig, always_2d=True, dtype="float32")
            dur = len(x) / sr
            entry["original"] = {"path": str(orig.relative_to(out)), "sha256": sha(orig), "sample_rate": sr,
                                 "channels": x.shape[1], "frames": len(x), "seconds": dur,
                                 "peak": float(np.max(np.abs(x))), "rms": float(np.sqrt(np.mean(x * x)))}
            if not np.isfinite(x).all() or abs(dur - secs) > max(2.0, 0.05 * secs) or entry["original"]["rms"] < 1e-5:
                raise RuntimeError(f"{name}: not finite, silent or {dur:.1f} s instead of {secs} s")
            n = round(fade * sr)
            if fade > 0 and 2 * n >= len(x):
                entry["loop"] = {"skipped": f"crossfade {fade} s is not under half of {dur:.1f} s"}
            elif fade > 0:
                # Overlap crossfade: the tail fades into the head, so N frames become N - fade frames.
                gain = np.linspace(0, 1, n, endpoint=False, dtype=np.float32)[:, None]
                loop = np.concatenate([x[n:-n], x[-n:] * (1 - gain) + x[:n] * gain], axis=0)
                scale = min(1.0, (10 ** (-1 / 20)) / max(float(np.max(np.abs(loop))), 1e-9))
                loop *= scale
                (out / "loops").mkdir(exist_ok=True)
                (out / "seams").mkdir(exist_ok=True)
                wav = out / "loops" / f"{name}.wav"
                sf.write(wav, loop, sr, subtype="PCM_16")
                wrap = out / "seams" / f"{name}-wrap.wav"
                sf.write(wrap, np.concatenate([loop[-12 * sr:], loop[:12 * sr]]), sr, subtype="PCM_16")
                entry["loop"] = {"path": str(wav.relative_to(out)), "sha256": sha(wav), "frames": len(loop),
                                 "crossfade_seconds": n / sr, "gain": scale, "wrap_audition": str(wrap.relative_to(out)),
                                 "seam_review": "not_run"}
            save()
            print("DONE", name, entry["generate_seconds"], "s", flush=True)
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

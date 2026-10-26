"""Fun-CosyVoice3 worker: zero-shot from the private reference and its exact
transcript, or instruct2 (the same reference plus a spoken-style instruction)
when a cue has controls.instruct. One take per cue and seed; multi-sentence
output segments are joined in order. Reads speed and instruct only."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
from speech_common import Session  # noqa: E402

plan, model_dir, out, inputs = sys.argv[1:5]
s = Session(HERE, plan, model_dir, out, inputs)
SYSTEM = "You are a helpful assistant."


def load(path):
    from cosyvoice.cli.cosyvoice import CosyVoice3

    return CosyVoice3(str(path), load_trt=False, load_vllm=False, fp16=False)


def take(model, cue, seed, controls, ref):
    import torch

    speed = float(controls.get("speed", 1.0))
    if controls.get("instruct"):
        parts = model.inference_instruct2(cue["text"], f"{SYSTEM} {controls['instruct']}<|endofprompt|>", ref["path"],
                                          stream=False, speed=speed)
    else:
        parts = model.inference_zero_shot(cue["text"], f"{SYSTEM}<|endofprompt|>{ref['transcript']}", ref["path"],
                                          stream=False, speed=speed)
    wav = torch.cat([p["tts_speech"] for p in parts], dim=1)
    return wav.squeeze(0).cpu().numpy(), model.sample_rate


s.run(load, take)

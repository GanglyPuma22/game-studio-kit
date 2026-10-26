"""Qwen3-TTS Base worker: one voice-clone prompt from the private reference
and its exact transcript (full mode, not x-vector only), then one take per
cue and seed. Base has no instruction input, so delivery stays intent only."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
from speech_common import Session  # noqa: E402

plan, model_dir, out, inputs = sys.argv[1:5]
s = Session(HERE, plan, model_dir, out, inputs)
LANG = {"en": "English"}


def typed(c):
    return {k: int(v) if k == "top_k" else float(v) for k, v in c.items()}
state = {}


def load(path):
    import torch
    from qwen_tts import Qwen3TTSModel

    state.clear()
    return Qwen3TTSModel.from_pretrained(str(path), dtype=torch.bfloat16, device_map="cuda:0", attn_implementation="sdpa")


def take(model, cue, seed, controls, ref):
    if "prompt" not in state:
        state["prompt"] = model.create_voice_clone_prompt(ref_audio=ref["path"], ref_text=ref["transcript"],
                                                          x_vector_only_mode=False)
    wavs, sr = model.generate_voice_clone(text=cue["text"], language=LANG[s.plan["language"]],
                                          voice_clone_prompt=state["prompt"], **typed(controls))
    return wavs[0], sr


s.run(load, take)

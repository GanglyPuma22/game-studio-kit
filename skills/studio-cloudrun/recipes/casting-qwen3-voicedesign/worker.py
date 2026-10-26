"""Qwen3-TTS VoiceDesign worker: an original voice from a written description
(controls.instruct), one take per cue and seed. The takes are casting
candidates: a person picks one, and only that becomes a character's private
reference for the speech recipes."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
from speech_common import Session  # noqa: E402

plan, model_dir, out = sys.argv[1:4]
s = Session(HERE, plan, model_dir, out)
LANG = {"en": "English"}


def load(path):
    import torch
    from qwen_tts import Qwen3TTSModel

    return Qwen3TTSModel.from_pretrained(str(path), dtype=torch.bfloat16, device_map="cuda:0", attn_implementation="sdpa")


def take(model, cue, seed, controls, ref):
    controls = dict(controls)
    instruct = controls.pop("instruct")
    wavs, sr = model.generate_voice_design(text=cue["text"], instruct=instruct, language=LANG[s.plan["language"]],
                                         **{k: int(v) if k == "top_k" else float(v) for k, v in controls.items()})
    return wavs[0], sr


s.run(load, take)

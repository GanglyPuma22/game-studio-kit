"""Chatterbox worker: the private reference conditions the model once, then
one take per cue and seed (speech_common does the loop, files and receipt).
Chatterbox reads exaggeration, cfg_weight and temperature; nothing else."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
from speech_common import Session  # noqa: E402

plan, model_dir, out, inputs = sys.argv[1:5]
s = Session(HERE, plan, model_dir, out, inputs)
state = {}


def load(path):
    from chatterbox.tts import ChatterboxTTS

    state.pop("exaggeration", None)
    return ChatterboxTTS.from_local(path, "cuda")


def take(model, cue, seed, controls, ref):
    ex = float(controls.get("exaggeration", 0.5))
    if state.get("exaggeration") != ex:
        # Conditioning depends on exaggeration: redo it only when that changes.
        model.prepare_conditionals(ref["path"], exaggeration=ex)
        state["exaggeration"] = ex
    wav = model.generate(cue["text"], exaggeration=ex, cfg_weight=float(controls.get("cfg_weight", 0.5)),
                         temperature=float(controls.get("temperature", 0.8)))
    return wav.squeeze(0).cpu().numpy(), model.sr


s.run(load, take)

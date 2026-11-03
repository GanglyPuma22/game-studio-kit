"""Run MotionBricks on CPU: ONNX Runtime replaces TensorRT, Warp runs on its CPU device.

Import this before any motionbricks module. Then use MotionBricksSOMAEngine as usual.
"""
import json, sys, types, contextlib
from pathlib import Path
import numpy as np

# The package imports tensorrt at module level; give it an empty stand-in.
_trt = types.ModuleType("tensorrt")
_trt.__version__ = "10.8.0.43"
class _Any:
    def __getattr__(self, k): return _Any()
    def __call__(self, *a, **k): return _Any()
for name in ("Logger", "ILogger", "IProgressMonitor", "Runtime", "Builder", "OnnxParser",
             "BuilderFlag", "NetworkDefinitionCreationFlag", "MemoryPoolType", "TensorIOMode",
             "DataType", "nptype", "init_libnvinfer_plugins"):
    setattr(_trt, name, _Any())
class _PM:  # progress monitor base class
    pass
_trt.IProgressMonitor = _PM
_trt.ILogger = type("ILogger", (), {"Severity": _Any()})
_trt.Logger = type("Logger", (), {"__init__": lambda self, *a: None, "Severity": _Any(),
                                  "INTERNAL_ERROR": 0, "ERROR": 1, "WARNING": 2, "INFO": 3, "VERBOSE": 4})
sys.modules["tensorrt"] = _trt

import warp as wp
wp.config.quiet = True
wp.init()
wp.set_device("cpu")

import onnxruntime as ort
from motionbricks.inference import engine as _ie
from motionbricks.inference.types import TensorSpec, TensorMode
from motionbricks.model import generation as _gen
from motionbricks.model import engine as _me


class _NoTimer:
    def __init__(self, *_a, **_k):
        self.milliseconds = {}
    @contextlib.contextmanager
    def stage(self, _n):
        yield
    def read(self):
        pass

_me.GenerationTimer = _NoTimer


def _init(self, onnx_path, *, build_options=None, stream=None, cache_dir=None,
          force_rebuild=False, logger_severity="INFO", build_progress_monitor=None):
    self._closed = False
    self._onnx_path = Path(onnx_path)
    self._cuda_graph = None
    so = ort.SessionOptions()
    so.intra_op_num_threads = 0
    self._session = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    manifest = next(Path(onnx_path).parent.glob("*_n1.json"))
    specs = json.loads(manifest.read_text())["tensor_specs"]
    self._tensor_specs = {s["name"]: TensorSpec(s["name"], TensorMode(s["mode"]), tuple(s["shape"]),
                                                np.dtype(s["dtype"])) for s in specs}
    self._buffers = {n: wp.zeros(s.shape, dtype=wp.dtype_from_numpy(s.dtype), device="cpu")
                     for n, s in self._tensor_specs.items()}
    self._inputs = [n for n, s in self._tensor_specs.items() if s.mode == TensorMode.INPUT]
    self._outputs = [o.name for o in self._session.get_outputs()]


def _enqueue(self):
    feed = {n: self._buffers[n].numpy() for n in self._inputs}
    for name, value in zip(self._outputs, self._session.run(self._outputs, feed)):
        self._buffers[name].assign(wp.array(value.astype(self._buffers[name].numpy().dtype), device="cpu"))


_ie.InferenceEngine.__init__ = _init
_ie.InferenceEngine.device = property(lambda self: wp.get_device("cpu"))
_ie.InferenceEngine.stream = property(lambda self: None)
_ie.InferenceEngine.cuda_graph_baked = property(lambda self: True)
_ie.InferenceEngine.enqueue_async = _enqueue
_ie.InferenceEngine.synchronize = lambda self: None
_ie.InferenceEngine.bake_cuda_graph = lambda self: None
_ie.InferenceEngine._discard_resources = lambda self, synchronize=False: self._buffers.clear()

"""Self-contained RT-DETRv2 detector core (no ROS dependency).

Pipeline: :func:`preprocess` -> :class:`DetectorBackend` -> :func:`postprocess`,
orchestrated by :class:`RtDetrDetector`.
"""

from .backends import DetectorBackend, MockBackend, load_tensorrt_backend
from .detector import RtDetrDetector
from .postprocess import postprocess
from .preprocess import preprocess
from .types import Detection

__all__ = [
    "Detection",
    "DetectorBackend",
    "MockBackend",
    "load_tensorrt_backend",
    "RtDetrDetector",
    "preprocess",
    "postprocess",
]

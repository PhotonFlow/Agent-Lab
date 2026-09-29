"""Interchangeable RT-DETR inference backends."""

from .base import DetectorBackend
from .mock_backend import MockBackend

__all__ = ["DetectorBackend", "MockBackend", "load_tensorrt_backend"]


def load_tensorrt_backend(*args, **kwargs):
    """Lazily import and construct :class:`TensorRTBackend`.

    Imported on demand so ``import ...rtdetr.backends`` never pulls in
    ``tensorrt`` / ``pycuda``.
    """
    from .tensorrt_backend import TensorRTBackend

    return TensorRTBackend(*args, **kwargs)

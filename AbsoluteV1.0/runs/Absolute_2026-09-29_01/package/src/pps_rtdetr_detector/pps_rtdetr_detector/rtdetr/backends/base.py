"""Backend abstraction for RT-DETRv2 inference.

A backend takes the preprocessed deploy inputs and returns the raw deploy
outputs keyed by tensor name (``labels``, ``boxes``, ``scores``). This keeps the
pre/post-processing and the ROS node completely independent of the inference
engine, so a TensorRT engine and a deterministic mock are interchangeable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class DetectorBackend(ABC):
    @property
    @abstractmethod
    def input_hw(self) -> tuple[int, int]:
        """The square network input size as ``(H, W)`` (e.g. ``(640, 640)``)."""

    @abstractmethod
    def infer(self, images: np.ndarray, orig_target_sizes: np.ndarray) -> dict[str, np.ndarray]:
        """Run inference.

        Parameters
        ----------
        images: ``(N, 3, H, W) float32`` preprocessed batch.
        orig_target_sizes: ``(N, 2) int64`` original ``[W, H]`` per image.

        Returns
        -------
        dict with keys ``"labels"``, ``"boxes"``, ``"scores"`` (numpy arrays).
        """

    def close(self) -> None:  # pragma: no cover - default no-op
        """Release any backend resources (GPU buffers, engine, ...)."""

"""Deterministic mock backend (no native deps).

Returns a fixed set of detections in the RT-DETR deploy output format so the
full pipeline can be exercised in CI / launch tests before a real engine
exists. Boxes are given directly in original-image pixels (exactly what the
deploy postprocessor emits), so they pass through ``postprocess`` unchanged.
"""

from __future__ import annotations

import numpy as np

from .base import DetectorBackend


class MockBackend(DetectorBackend):
    def __init__(
        self,
        *,
        input_size: int = 640,
        boxes_xyxy: list[list[float]] | np.ndarray | None = None,
        scores: list[float] | np.ndarray | None = None,
        labels: list[int] | np.ndarray | None = None,
    ):
        self._input_size = int(input_size)
        if boxes_xyxy is None or len(boxes_xyxy) == 0:
            # A single, centred placeholder box; callers normally override this.
            boxes_xyxy = [[0.0, 0.0, 1.0, 1.0]]
            scores = [0.0]
            labels = [0]
        boxes = np.asarray(boxes_xyxy, dtype=np.float32).reshape(-1, 4)
        n = boxes.shape[0]
        self._boxes = boxes
        self._scores = np.asarray(
            scores if scores is not None else [0.9] * n, dtype=np.float32
        ).reshape(n)
        self._labels = np.asarray(
            labels if labels is not None else [0] * n, dtype=np.int64
        ).reshape(n)

    @property
    def input_hw(self) -> tuple[int, int]:
        return (self._input_size, self._input_size)

    def infer(self, images: np.ndarray, orig_target_sizes: np.ndarray) -> dict[str, np.ndarray]:
        batch = int(images.shape[0])
        return {
            "labels": np.repeat(self._labels[None, :], batch, axis=0),
            "boxes": np.repeat(self._boxes[None, :, :], batch, axis=0),
            "scores": np.repeat(self._scores[None, :], batch, axis=0),
        }

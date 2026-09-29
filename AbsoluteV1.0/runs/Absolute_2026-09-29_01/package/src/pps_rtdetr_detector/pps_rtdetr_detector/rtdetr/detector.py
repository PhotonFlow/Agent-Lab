"""RT-DETRv2 detector orchestrator (backend-agnostic).

Glues preprocess -> backend.infer -> postprocess into a single ``detect`` call
returning a list of :class:`Detection`. Has no ROS dependency, so it is unit
testable on its own with the mock backend.
"""

from __future__ import annotations

import numpy as np

from .backends.base import DetectorBackend
from .postprocess import postprocess
from .preprocess import preprocess
from .types import Detection


class RtDetrDetector:
    def __init__(
        self,
        backend: DetectorBackend,
        *,
        score_threshold: float = 0.5,
        pallet_class_id: int | None = 0,
        max_detections: int = 10,
    ):
        self.backend = backend
        self.score_threshold = float(score_threshold)
        self.pallet_class_id = pallet_class_id
        self.max_detections = int(max_detections)
        self._input_size = int(backend.input_hw[0])

    def detect(self, image_rgb: np.ndarray) -> list[Detection]:
        height, width = int(image_rgb.shape[0]), int(image_rgb.shape[1])
        images, orig_target_sizes = preprocess(image_rgb, input_size=self._input_size)
        outputs = self.backend.infer(images, orig_target_sizes)
        return postprocess(
            outputs,
            score_threshold=self.score_threshold,
            pallet_class_id=self.pallet_class_id,
            max_detections=self.max_detections,
            image_wh=(width, height),
        )

    def close(self) -> None:
        self.backend.close()

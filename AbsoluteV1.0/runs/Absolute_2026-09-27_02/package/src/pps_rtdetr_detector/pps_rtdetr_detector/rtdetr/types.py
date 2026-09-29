"""Lightweight detection type shared across the detector core."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Detection:
    """A single 2D detection in original (rectified) RGB pixel coordinates.

    Attributes
    ----------
    bbox_xyxy: ``(4,) float64`` axis-aligned box ``[x1, y1, x2, y2]``.
    score: detection confidence in ``[0, 1]``.
    label: integer class id (0 = pallet for the binary detector).
    """

    bbox_xyxy: np.ndarray
    score: float
    label: int

    @property
    def width(self) -> float:
        return float(self.bbox_xyxy[2] - self.bbox_xyxy[0])

    @property
    def height(self) -> float:
        return float(self.bbox_xyxy[3] - self.bbox_xyxy[1])

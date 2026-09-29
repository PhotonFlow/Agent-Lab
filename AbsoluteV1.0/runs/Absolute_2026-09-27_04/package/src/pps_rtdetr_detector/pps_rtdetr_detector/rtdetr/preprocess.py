"""RT-DETRv2 deploy preprocessing.

Matches the official ``lyuwenyu/RT-DETR`` deploy contract exactly:
  * resize to ``input_size`` x ``input_size`` (no aspect-ratio preservation /
    no letterbox -- the baked-in postprocessor rescales boxes using
    ``orig_target_sizes``),
  * scale to ``[0, 1]`` by dividing by 255 (RT-DETR uses no mean/std),
  * CHW float32, batched,
  * ``orig_target_sizes = [width, height]`` (int64), so the engine's
    postprocessor maps boxes back to original-image pixels.

Input is expected as an ``(H, W, 3)`` uint8 **RGB** image (the node decodes the
ROS Image into RGB before calling this).
"""

from __future__ import annotations

import cv2
import numpy as np


def preprocess(
    image_rgb: np.ndarray, *, input_size: int = 640
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(images[1,3,S,S] f32, orig_target_sizes[1,2] i64)``."""
    if image_rgb.ndim != 3 or image_rgb.shape[2] != 3:
        raise ValueError(f"expected (H, W, 3) RGB image, got shape {image_rgb.shape}")
    height, width = int(image_rgb.shape[0]), int(image_rgb.shape[1])

    resized = cv2.resize(
        image_rgb, (int(input_size), int(input_size)), interpolation=cv2.INTER_LINEAR
    )
    chw = resized.astype(np.float32).transpose(2, 0, 1) / np.float32(255.0)
    images = np.ascontiguousarray(chw[None, ...], dtype=np.float32)  # (1, 3, S, S)
    orig_target_sizes = np.array([[width, height]], dtype=np.int64)  # (1, 2) = [W, H]
    return images, orig_target_sizes

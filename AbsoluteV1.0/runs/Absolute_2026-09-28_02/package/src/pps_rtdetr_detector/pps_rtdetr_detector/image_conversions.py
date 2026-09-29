"""Decode a ``sensor_msgs/Image`` into an ``(H, W, 3)`` uint8 RGB array.

Avoids a hard dependency on ``cv_bridge`` (numpy-only), and honours ``step``.
Supports the common color encodings; RT-DETR consumes RGB.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def image_to_rgb(msg: Any) -> np.ndarray:
    height, width, step = int(msg.height), int(msg.width), int(msg.step)
    enc = msg.encoding
    raw = np.frombuffer(bytes(msg.data), dtype=np.uint8)

    if enc in ("rgb8", "bgr8"):
        row_bytes = width * 3
        if raw.size < height * step or step < row_bytes:
            raise ValueError(f"image buffer too small for {enc}: size={raw.size}, step={step}")
        img = np.ascontiguousarray(
            raw[: height * step].reshape(height, step)[:, :row_bytes]
        ).reshape(height, width, 3)
        if enc == "bgr8":
            img = img[:, :, ::-1]
        return np.ascontiguousarray(img)

    if enc == "mono8":
        if raw.size < height * step or step < width:
            raise ValueError(f"image buffer too small for mono8: size={raw.size}, step={step}")
        gray = np.ascontiguousarray(
            raw[: height * step].reshape(height, step)[:, :width]
        ).reshape(height, width)
        return np.repeat(gray[:, :, None], 3, axis=2)

    raise ValueError(f"Unsupported image encoding: {enc!r} (expected rgb8/bgr8/mono8)")

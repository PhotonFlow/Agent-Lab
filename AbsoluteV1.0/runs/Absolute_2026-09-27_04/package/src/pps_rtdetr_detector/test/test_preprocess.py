"""Unit tests for RT-DETR deploy preprocessing."""

from __future__ import annotations

import numpy as np

from pps_rtdetr_detector.rtdetr.preprocess import preprocess


def test_shapes_and_orig_target_sizes():
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    images, orig = preprocess(img, input_size=640)
    assert images.shape == (1, 3, 640, 640)
    assert images.dtype == np.float32
    assert orig.shape == (1, 2)
    assert orig.dtype == np.int64
    # orig_target_sizes is [W, H], not [H, W].
    assert orig[0, 0] == 1920
    assert orig[0, 1] == 1080


def test_scaling_to_unit_range():
    img = np.full((100, 200, 3), 255, dtype=np.uint8)
    images, _ = preprocess(img, input_size=64)
    assert np.isclose(images.max(), 1.0)
    assert np.isclose(images.min(), 1.0)


def test_rejects_non_rgb():
    try:
        preprocess(np.zeros((10, 10), dtype=np.uint8))
    except ValueError:
        return
    raise AssertionError("expected ValueError for non-3-channel input")

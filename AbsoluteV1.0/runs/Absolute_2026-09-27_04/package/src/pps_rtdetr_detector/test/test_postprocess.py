"""Unit tests for RT-DETR deploy postprocessing."""

from __future__ import annotations

import numpy as np

from pps_rtdetr_detector.rtdetr.postprocess import postprocess


def _outputs():
    # Three candidates: a strong pallet, a weak pallet, a strong non-pallet.
    labels = np.array([[0, 0, 1]], dtype=np.int64)
    scores = np.array([[0.9, 0.2, 0.95]], dtype=np.float32)
    boxes = np.array(
        [[[100, 100, 300, 260], [10, 10, 20, 20], [500, 500, 700, 700]]], dtype=np.float32
    )
    return {"labels": labels, "scores": scores, "boxes": boxes}


def test_threshold_and_class_filter():
    dets = postprocess(
        _outputs(),
        score_threshold=0.5,
        pallet_class_id=0,
        max_detections=10,
        image_wh=(1920, 1080),
    )
    # Only the strong pallet survives (weak pallet below threshold, class 1 filtered).
    assert len(dets) == 1
    assert dets[0].label == 0
    assert dets[0].score == np.float32(0.9)
    np.testing.assert_allclose(dets[0].bbox_xyxy, [100, 100, 300, 260])


def test_max_detections_and_sort():
    out = _outputs()
    out["labels"] = np.array([[0, 0, 0]], dtype=np.int64)
    out["scores"] = np.array([[0.6, 0.99, 0.7]], dtype=np.float32)
    dets = postprocess(
        out, score_threshold=0.5, pallet_class_id=0, max_detections=2, image_wh=(1920, 1080)
    )
    assert len(dets) == 2
    assert dets[0].score >= dets[1].score  # sorted descending
    assert np.isclose(dets[0].score, 0.99)


def test_clip_to_image_bounds():
    out = {
        "labels": np.array([[0]], dtype=np.int64),
        "scores": np.array([[0.9]], dtype=np.float32),
        "boxes": np.array([[[-50, -20, 5000, 5000]]], dtype=np.float32),
    }
    dets = postprocess(
        out, score_threshold=0.5, pallet_class_id=0, max_detections=10, image_wh=(1920, 1080)
    )
    assert len(dets) == 1
    b = dets[0].bbox_xyxy
    assert b[0] >= 0 and b[1] >= 0
    assert b[2] <= 1919 and b[3] <= 1079


def test_class_none_keeps_all_classes():
    dets = postprocess(
        _outputs(),
        score_threshold=0.5,
        pallet_class_id=None,
        max_detections=10,
        image_wh=(1920, 1080),
    )
    assert len(dets) == 2  # both strong detections regardless of class

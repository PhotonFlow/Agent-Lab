"""End-to-end detector-core test against the mock backend."""

from __future__ import annotations

import numpy as np

from pps_rtdetr_detector.rtdetr import MockBackend, RtDetrDetector


def test_detector_returns_configured_box():
    bbox = [329.0, 321.0, 1605.0, 747.0]
    backend = MockBackend(input_size=640, boxes_xyxy=[bbox], scores=[0.95], labels=[0])
    detector = RtDetrDetector(backend, score_threshold=0.5, pallet_class_id=0, max_detections=10)

    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    dets = detector.detect(image)

    assert len(dets) == 1
    assert dets[0].label == 0
    assert dets[0].score >= 0.5
    np.testing.assert_allclose(dets[0].bbox_xyxy, bbox)


def test_detector_filters_below_threshold():
    backend = MockBackend(
        input_size=640, boxes_xyxy=[[10, 10, 100, 100]], scores=[0.1], labels=[0]
    )
    detector = RtDetrDetector(backend, score_threshold=0.5, pallet_class_id=0)
    dets = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))
    assert dets == []


def test_input_size_propagates_from_backend():
    backend = MockBackend(input_size=512)
    detector = RtDetrDetector(backend)
    assert detector._input_size == 512

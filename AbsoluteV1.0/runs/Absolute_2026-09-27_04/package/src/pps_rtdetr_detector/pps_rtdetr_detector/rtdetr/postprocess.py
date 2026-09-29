"""RT-DETRv2 deploy postprocessing.

The deploy engine already applies sigmoid + top-k decoding and rescales boxes to
original-image pixels, so its outputs are ``labels``, ``boxes`` (xyxy), and
``scores`` for ``num_top_queries`` candidates. Here we only:
  * threshold by score,
  * keep the target (pallet) class for the binary detector,
  * sort by score and cap to ``max_detections``,
  * clip boxes to the image.

No NMS is needed -- RT-DETR is NMS-free by design.
"""

from __future__ import annotations

import numpy as np

from .types import Detection


def postprocess(
    outputs: dict,
    *,
    score_threshold: float,
    pallet_class_id: int | None,
    max_detections: int,
    image_wh: tuple[int, int],
) -> list[Detection]:
    labels = np.asarray(outputs["labels"]).reshape(-1)
    scores = np.asarray(outputs["scores"]).reshape(-1)
    boxes = np.asarray(outputs["boxes"]).reshape(-1, 4)
    if not (labels.shape[0] == scores.shape[0] == boxes.shape[0]):
        raise ValueError(
            f"inconsistent output lengths: labels={labels.shape}, scores={scores.shape}, "
            f"boxes={boxes.shape}"
        )

    keep = scores >= float(score_threshold)
    if pallet_class_id is not None:
        keep &= labels == int(pallet_class_id)
    idx = np.nonzero(keep)[0]
    idx = idx[np.argsort(scores[idx])[::-1]]  # high score first
    if max_detections and max_detections > 0:
        idx = idx[: int(max_detections)]

    width, height = int(image_wh[0]), int(image_wh[1])
    detections: list[Detection] = []
    for i in idx:
        x1, y1, x2, y2 = (float(v) for v in boxes[i])
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        x1 = float(np.clip(x1, 0.0, width - 1.0))
        x2 = float(np.clip(x2, 0.0, width - 1.0))
        y1 = float(np.clip(y1, 0.0, height - 1.0))
        y2 = float(np.clip(y2, 0.0, height - 1.0))
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append(
            Detection(
                bbox_xyxy=np.array([x1, y1, x2, y2], dtype=np.float64),
                score=float(scores[i]),
                label=int(labels[i]),
            )
        )
    return detections

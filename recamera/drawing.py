"""
Drawing and rendering utilities for bounding boxes and labels.
"""

from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np


def draw_detections(
    frame: np.ndarray,
    boxes: List[Dict],
    labels: Optional[List[str]] = None,
    color: Tuple[int, int, int] = (0, 255, 0),
    thickness: int = 2,
    font_scale: float = 0.55,
) -> np.ndarray:
    """
    Draw bounding boxes and class labels onto an image frame.

    :param frame: BGR image from OpenCV.
    :param boxes: List of detection dictionaries (with x, y, w, h, score, class_id).
    :param labels: Optional list mapping class ID indices to human-readable names.
    :param color: Bounding box BGR color.
    :param thickness: Line thickness.
    :param font_scale: OpenCV font scale.
    :return: Rendered frame.
    """
    labels = labels or []
    h, w, _ = frame.shape
    out = frame.copy()

    for b in boxes:
        x = b.get("x", 0)
        y = b.get("y", 0)
        bw = b.get("w", 0)
        bh = b.get("h", 0)
        score = float(b.get("score", 0.0))
        cls_id = int(b.get("class_id", 0))

        # Detect normalized coords ([0, 1]) vs pixel coords
        if x <= 1.0 and y <= 1.0 and bw <= 1.0 and bh <= 1.0:
            cx, cy, box_w, box_h = x * w, y * h, bw * w, bh * h
        else:
            cx, cy, box_w, box_h = x, y, bw, bh

        x1 = max(0, int(cx - box_w / 2))
        y1 = max(0, int(cy - box_h / 2))
        x2 = min(w - 1, int(cx + box_w / 2))
        y2 = min(h - 1, int(cy + box_h / 2))

        cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)

        label_name = labels[cls_id] if 0 <= cls_id < len(labels) else f"ID:{cls_id}"
        text = f"{label_name} {score:.2f}"
        cv2.putText(
            out,
            text,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            thickness,
        )

    return out

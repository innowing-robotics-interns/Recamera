"""Draw detection boxes onto a frame."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

DEFAULT_COLOR = (0, 255, 0)
# A label is drawn only if it clears this fraction of the frame height, so text
# never runs off the top of the image.
_LABEL_MARGIN = 0.03


def _as_int(value: float) -> int:
    return round(value)


def _point_in_frame(x: float, y: float, frame_w: int, frame_h: int) -> tuple[int, int]:
    return max(0, min(frame_w - 1, _as_int(x))), max(0, min(frame_h - 1, _as_int(y)))


def draw_detections(
    frame: np.ndarray,
    boxes: list[dict[str, Any]],
    labels: list[str] | None = None,
    color: tuple[int, int, int] = DEFAULT_COLOR,
    thickness: int = 2,
    font_scale: float = 0.55,
    resolution: tuple[int, int] | None = None,
) -> np.ndarray:
    """Draw ``boxes`` (as produced by :mod:`recamera.detections`) on ``frame``.

    Coordinates are expected in the same pixel space as ``frame``; pass
    ``resolution`` only if they are not, and each box is scaled in place.
    """
    labels = labels or []
    frame_h, frame_w = frame.shape[:2]
    out = frame.copy()
    margin = max(20, int(frame_h * _LABEL_MARGIN))

    for box in boxes:
        box = dict(box)
        if resolution and (resolution[0] != frame_w or resolution[1] != frame_h):
            from .detections import scale_box

            box = scale_box(box, (frame_w, frame_h), resolution)

        score = float(box.get("score", 0.0))
        class_id = int(box.get("class_id", 0))
        name = labels[class_id] if 0 <= class_id < len(labels) else f"ID:{class_id}"
        text = f"{name} {score:.2f}"

        corners = box.get("corners")
        if isinstance(corners, list) and len(corners) >= 4:
            points = np.array(
                [
                    [
                        _as_int(p["x"] if isinstance(p, dict) else p[0]),
                        _as_int(p["y"] if isinstance(p, dict) else p[1]),
                    ]
                    for p in corners[:4]
                ],
                dtype=np.int32,
            )
            cv2.polylines(out, [points], True, color, thickness)
            left, top = int(points[:, 0].min()), int(points[:, 1].min())
        else:
            cx, cy = float(box["x"]), float(box["y"])
            bw, bh = float(box["w"]), float(box["h"])
            angle = box.get("angle")
            if angle is not None:
                rad = float(angle)
                if abs(rad) > 6.3:  # the camera may report degrees
                    rad = float(np.radians(rad))
                points = cv2.boxPoints(((cx, cy), (bw, bh), float(np.degrees(rad)))).astype(np.int32)
                cv2.polylines(out, [points], True, color, thickness)
                left, top = int(points[:, 0].min()), int(points[:, 1].min())
            else:
                left, top = _point_in_frame(cx - bw / 2, cy - bh / 2, frame_w, frame_h)
                right, bottom = _point_in_frame(cx + bw / 2, cy + bh / 2, frame_w, frame_h)
                cv2.rectangle(out, (left, top), (right, bottom), color, thickness)

        text_x = max(0, min(left, frame_w - 1))
        text_y = max(margin, top - 8)
        cv2.putText(out, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness)

    return out

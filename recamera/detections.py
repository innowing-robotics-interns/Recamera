"""Normalisation of the detection payloads the camera publishes.

The camera is not consistent about units, so everything on the wire is put into
one shape here and nowhere else:

* ``score`` arrives as 0-100 (the dashboard prints ``{{score}}``), occasionally
  as 0-1. Both are normalised to 0.0-1.0.
* box coordinates are pixels in the *preview* resolution (1280x720 on firmware
  0.2.4), not in the RTSP resolution (1920x1080). The preview size is carried in
  ``resolution`` when the payload has it; otherwise callers pass it in.

Two payload families exist, both handled here:

* ``/ws/boxes`` on 1880 - objects in ``boxes``
  (``{"x", "y", "w", "h", "score", "class_id"}``), box lists are
  ``[x, y, w, h, score, class_id]``.
* the dashboard feed on 8090 - the same box lists plus ``resolution``, ``labels``
  and a base64 ``image`` of the preview frame.
"""

from __future__ import annotations

import base64
import json
from typing import Any

DEFAULT_PREVIEW = (1280, 720)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalise_score(value: Any) -> float:
    """Map a wire score to 0.0-1.0.

    The camera emits integer percentages, so ``69`` is 0.69. Values above 1 are
    divided by 100; everything else is assumed to be already normalised.
    """
    score = _as_float(value)
    if score > 1.0:
        score /= 100.0
    return max(0.0, min(1.0, score))


def _box_from_mapping(box: dict[str, Any]) -> dict[str, Any]:
    return {
        "x": _as_float(box.get("x")),
        "y": _as_float(box.get("y")),
        "w": _as_float(box.get("w", box.get("width"))),
        "h": _as_float(box.get("h", box.get("height"))),
        "score": normalise_score(box.get("score")),
        "class_id": int(_as_float(box.get("class_id", box.get("target", 0)))),
        "angle": box.get("angle"),
        "corners": box.get("corners") or box.get("obb_corners"),
    }


def _box_from_sequence(box: list[Any] | tuple[Any, ...]) -> dict[str, Any] | None:
    if len(box) < 4:
        return None
    return {
        "x": _as_float(box[0]),
        "y": _as_float(box[1]),
        "w": _as_float(box[2]),
        "h": _as_float(box[3]),
        "score": normalise_score(box[4]) if len(box) > 4 else 0.0,
        "class_id": int(_as_float(box[5])) if len(box) > 5 else 0,
        "angle": box[6] if len(box) > 6 else None,
        "corners": None,
    }


def normalise_box(box: Any) -> dict[str, Any] | None:
    if isinstance(box, dict):
        return _box_from_mapping(box)
    if isinstance(box, (list, tuple)):
        return _box_from_sequence(box)
    return None


def _decode_image(encoded: Any):
    """Decode a base64 JPEG from the dashboard feed, or return ``None``."""
    if not isinstance(encoded, str) or not encoded:
        return None
    try:
        import cv2
        import numpy as np

        raw = base64.b64decode(encoded)
        return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def parse_message(message: Any) -> dict[str, Any]:
    """Turn one websocket message into a normalised record.

    Returns ``{"boxes": [...], "resolution": (w, h) | None, "frame": ndarray | None,
    "labels": [...], "perf": {...}}``.
    """
    data: Any = message
    if isinstance(message, (str, bytes, bytearray)):
        try:
            data = json.loads(message)
        except (ValueError, UnicodeDecodeError):
            data = {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]

    boxes: list[Any] = []
    resolution = None
    labels: list[str] = []
    frame = None
    perf: dict[str, Any] = {}

    if isinstance(data, dict):
        boxes = data.get("boxes") or []
        resolution = _parse_resolution(data.get("resolution"))
        labels = [str(x) for x in (data.get("labels") or [])]
        frame = _decode_image(data.get("image"))
        perf = data.get("perf") or {}
    elif isinstance(data, list):
        # A bare list is either one box ([x, y, w, h, score, id]) or a list of
        # boxes ([[...], [...]]); distinguish by whether the first item is a
        # number.
        boxes = [data] if data and isinstance(data[0], (int, float)) else data

    parsed = [b for b in (normalise_box(box) for box in boxes) if b is not None]
    return {"boxes": parsed, "resolution": resolution, "labels": labels, "frame": frame, "perf": perf}


def _parse_resolution(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        width, height = _as_float(value[0]), _as_float(value[1])
        if width > 1 and height > 1:
            return int(width), int(height)
    return None


def scale_box(
    box: dict[str, Any],
    frame_size: tuple[int, int],
    source_size: tuple[int, int] | None,
) -> dict[str, Any]:
    """Rescale a box from ``source_size`` into ``frame_size`` (w, h)."""
    frame_w, frame_h = frame_size
    if not source_size:
        return box
    source_w, source_h = source_size
    if source_w <= 1 or source_h <= 1:
        return box
    if abs(source_w - frame_w) <= 1 and abs(source_h - frame_h) <= 1:
        return box

    scale_x = frame_w / source_w
    scale_y = frame_h / source_h
    scaled = dict(box)
    scaled["x"] = box["x"] * scale_x
    scaled["y"] = box["y"] * scale_y
    scaled["w"] = box["w"] * scale_x
    scaled["h"] = box["h"] * scale_y
    corners = box.get("corners")
    if isinstance(corners, list) and corners:
        scaled["corners"] = [_scale_point(point, scale_x, scale_y) for point in corners]
    return scaled


def _scale_point(point: Any, scale_x: float, scale_y: float) -> Any:
    if isinstance(point, dict):
        return {"x": _as_float(point.get("x")) * scale_x, "y": _as_float(point.get("y")) * scale_y}
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return [point[0] * scale_x, point[1] * scale_y]
    return point

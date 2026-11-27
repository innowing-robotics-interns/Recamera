"""Wire payloads are normalised to 0-1 scores and keep their coordinate space."""

import base64
import json

import cv2
import numpy as np
import pytest

from recamera.detections import normalise_box, normalise_score, parse_message, scale_box


@pytest.mark.parametrize(
    "raw, expected",
    [
        (69, 0.69),        # the camera's integer percentage
        (100, 1.0),
        (0, 0.0),
        (0.63, 0.63),      # already normalised
        (1, 1.0),
        (1.5, 0.015),
        ("71", 0.71),
        (None, 0.0),
        ("abc", 0.0),
        (-5, 0.0),
        (150, 1.0),
    ],
)
def test_normalise_score(raw, expected):
    assert normalise_score(raw) == pytest.approx(expected)


def test_html_boxes_payload_is_normalised():
    message = json.dumps(
        {
            "timestamp": 1,
            "boxes": [{"x": 102, "y": 388, "w": 81, "h": 81, "score": 63, "class_id": 0}],
            "keypoints": [],
            "segments": [],
        }
    )
    record = parse_message(message)
    box = record["boxes"][0]
    assert box["score"] == pytest.approx(0.63)
    assert (box["x"], box["y"], box["w"], box["h"]) == (102.0, 388.0, 81.0, 81.0)
    assert record["resolution"] is None


def test_dashboard_payload_carries_resolution_labels_and_frame():
    image = np.zeros((72, 128, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    message = json.dumps(
        {
            "code": 0,
            "data": {
                "boxes": [[102, 389, 81, 83, 66, 0]],
                "labels": ["screw", "nut"],
                "resolution": [1280, 720],
                "image": base64.b64encode(encoded.tobytes()).decode(),
            },
        }
    )
    record = parse_message(message)
    assert record["resolution"] == (1280, 720)
    assert record["labels"] == ["screw", "nut"]
    assert record["frame"] is not None and record["frame"].shape == (72, 128, 3)
    assert record["boxes"][0]["score"] == pytest.approx(0.66)
    assert record["boxes"][0]["class_id"] == 0


def test_plain_list_payload():
    record = parse_message([10, 20, 30, 40, 55, 2])
    assert record["boxes"] == [
        {
            "x": 10.0,
            "y": 20.0,
            "w": 30.0,
            "h": 40.0,
            "score": 0.55,
            "class_id": 2,
            "angle": None,
            "corners": None,
        }
    ]


def test_malformed_messages_do_not_raise():
    for message in (b"not json", "", None, 42, {"data": "x"}, {"boxes": "nope"}):
        record = parse_message(message)
        assert record["boxes"] == []


def test_scale_box_maps_preview_to_video_frame():
    box = {"x": 640, "y": 360, "w": 100, "h": 50, "score": 0.5, "class_id": 0}
    scaled = scale_box(box, (1920, 1080), (1280, 720))
    assert scaled["x"] == pytest.approx(960)
    assert scaled["y"] == pytest.approx(540)
    assert scaled["w"] == pytest.approx(150)
    assert scaled["h"] == pytest.approx(75)


def test_scale_box_is_a_noop_when_spaces_match():
    box = {"x": 1, "y": 2, "w": 3, "h": 4, "score": 0.5, "class_id": 0}
    result = scale_box(box, (1280, 720), (1280, 720))
    assert result is box


def test_normalise_box_rejects_short_input():
    assert normalise_box([1, 2, 3]) is None
    assert normalise_box("nope") is None

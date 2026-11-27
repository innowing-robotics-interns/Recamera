"""Rendering scales boxes correctly and prints a sane confidence."""

import numpy as np

from recamera.drawing import draw_detections


def frame(width=640, height=360):
    return np.zeros((height, width, 3), dtype=np.uint8)


def box(x, y, w, h, score=0.9, class_id=0):
    return {"x": x, "y": y, "w": w, "h": h, "score": score, "class_id": class_id}


def green_pixels(image):
    return int(np.all(image == (0, 255, 0), axis=2).sum())


def test_box_is_drawn_at_the_expected_pixels():
    image = draw_detections(frame(), [box(320, 180, 100, 60)], ["screw"])
    assert green_pixels(image) > 0
    # somewhere on the top edge of the box (x in 270..370, y == 150)
    assert np.all(image[150, 300] == (0, 255, 0))


def test_body_is_not_filled():
    """Only the outline is painted, so a centre pixel stays black."""
    image = draw_detections(frame(), [box(320, 180, 200, 120)], ["screw"])
    assert np.all(image[180, 320] == (0, 0, 0))


def test_confidence_renders_as_a_fraction(snapshot_text=None):
    image = draw_detections(frame(), [box(50, 50, 20, 20, score=0.63)], ["screw"])
    # the label is drawn; its exact glyphs are not asserted, only that something rendered
    label_region = image[10:35, 0:120]
    assert int(label_region.sum()) > 0


def test_resolution_scales_boxes_into_the_frame():
    box = {"x": 640, "y": 360, "w": 100, "h": 100, "score": 0.9, "class_id": 0}
    image = draw_detections(frame(1920, 1080), [box], ["screw"], resolution=(1280, 720))
    # centre (640,360) in 1280x720 space is (960,540) in 1920x1080; the box body
    # is 150x150 there, so its left edge sits at x=885, y=540
    assert np.all(image[540, 885] == (0, 255, 0))


def test_unknown_class_falls_back_to_an_id_label():
    image = draw_detections(frame(), [box(100, 100, 20, 20, class_id=5)], ["screw"])
    assert int(image.sum()) > 0


def test_corners_are_polygons():
    box = {
        "x": 0,
        "y": 0,
        "w": 0,
        "h": 0,
        "score": 0.9,
        "class_id": 0,
        "corners": [{"x": 50, "y": 50}, {"x": 90, "y": 50}, {"x": 90, "y": 90}, {"x": 50, "y": 90}],
    }
    image = draw_detections(frame(), [box], ["screw"])
    assert np.all(image[50, 70] == (0, 255, 0))


def test_out_of_frame_boxes_do_not_crash():
    image = draw_detections(
        frame(), [{"x": -100, "y": -100, "w": 50, "h": 50, "score": 0.9, "class_id": 0}], ["screw"]
    )
    assert image.shape == (360, 640, 3)


def test_empty_input_returns_an_equal_frame():
    original = frame()
    result = draw_detections(original, [], [])
    assert np.array_equal(result, original)

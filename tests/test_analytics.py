"""Zone capture and debouncing behave predictably."""

import pytest

from recamera.analytics import PersistenceFilter, ZoneMonitor


def box(cx, cy, score=0.9, class_id=0):
    return {"x": cx, "y": cy, "w": 10, "h": 10, "score": score, "class_id": class_id}


def test_zone_keeps_only_boxes_whose_centre_is_inside():
    zone = ZoneMonitor((100, 100, 200, 200))
    inside = zone.check([box(150, 150), box(50, 150), box(250, 150)])
    assert inside == [box(150, 150)]


def test_zone_is_order_independent():
    zone = ZoneMonitor((200, 200, 100, 100))
    assert zone.check([box(150, 150)]) == [box(150, 150)]


def test_zone_filters_by_score_and_class():
    zone = ZoneMonitor((0, 0, 100, 100), target_classes=[1], min_score=0.5)
    assert zone.check([box(10, 10, score=0.9, class_id=1)]) == [box(10, 10, score=0.9, class_id=1)]
    assert zone.check([box(10, 10, score=0.4, class_id=1)]) == []
    assert zone.check([box(10, 10, score=0.9, class_id=0)]) == []


def test_persistence_fires_once_after_required_frames():
    flt = PersistenceFilter(required_consecutive_frames=3, cooldown_frames=0)
    assert flt.update([box(0, 0)]) == []
    assert flt.update([box(0, 0)]) == []
    assert flt.update([box(0, 0)]) == [0]
    assert flt.update([box(0, 0)]) == [0]  # counting continues, cooldown is 0


def test_persistence_resets_when_the_class_disappears():
    flt = PersistenceFilter(required_consecutive_frames=2, cooldown_frames=0)
    flt.update([box(0, 0)])
    flt.update([])
    assert flt.update([box(0, 0)]) == []
    assert flt.update([box(0, 0)]) == [0]


def test_cooldown_suppresses_repeats():
    flt = PersistenceFilter(required_consecutive_frames=1, cooldown_frames=3)
    assert flt.update([box(0, 0)]) == [0]
    for _ in range(3):
        assert flt.update([box(0, 0)]) == []
    assert flt.update([box(0, 0)]) == [0]


def test_reset_clears_state():
    flt = PersistenceFilter(required_consecutive_frames=1, cooldown_frames=10)
    flt.update([box(0, 0)])
    flt.reset()
    assert flt.update([box(0, 0)]) == [0]


def test_required_frames_must_be_positive():
    with pytest.raises(ValueError):
        PersistenceFilter(required_consecutive_frames=0)

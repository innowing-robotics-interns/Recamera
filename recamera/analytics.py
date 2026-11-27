"""Zone monitoring and temporal filtering over detections."""

from __future__ import annotations

from typing import Any


class ZoneMonitor:
    """Reports detections whose centre falls inside a rectangle.

    Zone bounds are in whatever space the boxes are: pass normalised 0-1 bounds
    when the boxes are normalised, or the same pixel space otherwise.
    """

    def __init__(
        self,
        zone: tuple[float, float, float, float],
        target_classes: list[int] | None = None,
        min_score: float = 0.5,
    ):
        x1, y1, x2, y2 = zone
        self.x1, self.x2 = min(x1, x2), max(x1, x2)
        self.y1, self.y2 = min(y1, y2), max(y1, y2)
        self.target_classes = set(target_classes) if target_classes is not None else None
        self.min_score = min_score

    def check(self, boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        inside = []
        for box in boxes:
            if float(box.get("score", 0.0)) < self.min_score:
                continue
            class_id = int(box.get("class_id", 0))
            if self.target_classes is not None and class_id not in self.target_classes:
                continue
            cx = float(box.get("x", 0.0))
            cy = float(box.get("y", 0.0))
            if self.x1 <= cx <= self.x2 and self.y1 <= cy <= self.y2:
                inside.append(box)
        return inside


class PersistenceFilter:
    """Fires once a class has been seen for ``required`` frames in a row.

    After firing, the class is suppressed for ``cooldown`` frames so one object
    does not trigger on every frame.
    """

    def __init__(self, required_consecutive_frames: int = 3, cooldown_frames: int = 15):
        if required_consecutive_frames < 1:
            raise ValueError("required_consecutive_frames must be >= 1")
        self.required = required_consecutive_frames
        self.cooldown = max(0, cooldown_frames)
        self._counts: dict[int, int] = {}
        self._cooldowns: dict[int, int] = {}

    def update(self, boxes: list[dict[str, Any]]) -> list[int]:
        """Feed one frame of detections; return class IDs that just fired."""
        seen = {int(box.get("class_id", 0)) for box in boxes}
        triggered: list[int] = []
        newly_cooling: set[int] = set()

        for class_id in seen:
            self._counts[class_id] = self._counts.get(class_id, 0) + 1
            if self._cooldowns.get(class_id, 0) > 0:
                continue
            if self._counts[class_id] >= self.required:
                triggered.append(class_id)
                if self.cooldown:
                    self._cooldowns[class_id] = self.cooldown
                    newly_cooling.add(class_id)

        # Tick down cooldowns set in earlier frames; a class fired this frame
        # keeps its full cooldown. This makes ``cooldown_frames=N`` suppress
        # exactly N frames after the firing frame.
        for class_id in list(self._cooldowns):
            if class_id in newly_cooling:
                continue
            self._cooldowns[class_id] -= 1
            if self._cooldowns[class_id] <= 0:
                del self._cooldowns[class_id]

        for class_id in list(self._counts):
            if class_id not in seen:
                self._counts[class_id] = 0

        return sorted(triggered)

    def reset(self) -> None:
        self._counts.clear()
        self._cooldowns.clear()

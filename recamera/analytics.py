"""
Analytics and trigger utilities: ROI / zone monitoring, class filtering, debouncing.
"""

from typing import Callable, Dict, List, Optional, Tuple


class ZoneMonitor:
    """Monitors whether detected objects enter a specific rectangular region of interest."""

    def __init__(
        self,
        zone: Tuple[float, float, float, float],
        target_classes: Optional[List[int]] = None,
        min_score: float = 0.5,
    ):
        """
        :param zone: (x1, y1, x2, y2) bounds. Normalized [0, 1] or pixel coordinates.
        :param target_classes: Optional list of class IDs to filter for.
        :param min_score: Minimum confidence threshold.
        """
        self.x1, self.y1, self.x2, self.y2 = zone
        self.target_classes = set(target_classes) if target_classes is not None else None
        self.min_score = min_score

    def check(self, boxes: List[Dict]) -> List[Dict]:
        """Return all detections whose center point falls inside the zone."""
        inside = []
        for b in boxes:
            score = float(b.get("score", 0.0))
            if score < self.min_score:
                continue

            cls_id = int(b.get("class_id", 0))
            if self.target_classes is not None and cls_id not in self.target_classes:
                continue

            cx = float(b.get("x", 0.0))
            cy = float(b.get("y", 0.0))

            if self.x1 <= cx <= self.x2 and self.y1 <= cy <= self.y2:
                inside.append(b)

        return inside


class PersistenceFilter:
    """
    Suppresses transient false positives by requiring a class detection
    to persist over consecutive frames.
    """

    def __init__(self, required_consecutive_frames: int = 3, cooldown_frames: int = 15):
        self.required = required_consecutive_frames
        self.cooldown = cooldown_frames
        self._counts: Dict[int, int] = {}
        self._cooldowns: Dict[int, int] = {}

    def update(self, boxes: List[Dict]) -> List[int]:
        """
        Feed new detections. Returns list of class IDs that triggered a persistent event.
        """
        detected_classes = {int(b.get("class_id", 0)) for b in boxes}
        triggered = []

        # Tick active cooldowns
        for cls_id in list(self._cooldowns.keys()):
            self._cooldowns[cls_id] -= 1
            if self._cooldowns[cls_id] <= 0:
                del self._cooldowns[cls_id]

        for cls_id in detected_classes:
            self._counts[cls_id] = self._counts.get(cls_id, 0) + 1
            if self._counts[cls_id] >= self.required:
                if cls_id not in self._cooldowns:
                    triggered.append(cls_id)
                    self._cooldowns[cls_id] = self.cooldown
        
        # Reset counters for classes not present in this frame
        for cls_id in list(self._counts.keys()):
            if cls_id not in detected_classes:
                self._counts[cls_id] = 0

        return triggered

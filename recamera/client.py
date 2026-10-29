"""
Main client entry point for the recamera SDK.
"""

import os
from typing import Callable, Dict, List, Optional, Tuple
import cv2
import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .analytics import PersistenceFilter, ZoneMonitor
from .api import ReCameraAPI
from .drawing import draw_detections
from .stream import StreamReceiver


class ReCamera:
    """Unified client for Seeed Studio reCamera."""

    def __init__(
        self,
        camera_ip: Optional[str] = None,
        labels: Optional[List[str]] = None,
        rtsp_port: Optional[int] = None,
        rtsp_path: Optional[str] = None,
        rtsp_username: Optional[str] = None,
        rtsp_password: Optional[str] = None,
        ws_port: Optional[int] = None,
        ws_path: Optional[str] = None,
        api_port: Optional[int] = None,
    ):
        self.camera_ip = camera_ip or os.getenv("RECAMERA_IP", "192.168.42.1")
        self.labels = labels or []

        _rtsp_port = rtsp_port or int(os.getenv("RECAMERA_RTSP_PORT", "554"))
        _rtsp_path = rtsp_path or os.getenv("RECAMERA_RTSP_PATH", "/live")
        _rtsp_user = rtsp_username if rtsp_username is not None else os.getenv("RECAMERA_RTSP_USER", "admin")
        _rtsp_pass = rtsp_password if rtsp_password is not None else os.getenv("RECAMERA_RTSP_PASS", "admin")

        _ws_port = ws_port or int(os.getenv("RECAMERA_WS_PORT", "1880"))
        _ws_path = ws_path or os.getenv("RECAMERA_WS_PATH", "/ws/boxes")
        _api_port = api_port or int(os.getenv("RECAMERA_API_PORT", "80"))

        self.api = ReCameraAPI(camera_ip=self.camera_ip, port=_api_port)
        self._stream = StreamReceiver(
            camera_ip=self.camera_ip,
            rtsp_port=_rtsp_port,
            rtsp_path=_rtsp_path,
            rtsp_username=_rtsp_user,
            rtsp_password=_rtsp_pass,
            ws_port=_ws_port,
            ws_path=_ws_path,
            labels=self.labels,
        )

    def connect(self) -> bool:
        """Start the video and metadata streams."""
        return self._stream.start()

    def disconnect(self) -> None:
        """Disconnect and release resources."""
        self._stream.stop()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray], List[Dict]]:
        """
        Read the next video frame and latest bounding boxes.
        :return: (success, frame, boxes)
        """
        return self._stream.read_frame()

    def draw(self, frame: np.ndarray, boxes: Optional[List[Dict]] = None) -> np.ndarray:
        """Draw detections onto a frame."""
        return self._stream.draw(frame, boxes)

    def snapshot(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Grab a single current video frame."""
        return self._stream.snapshot()

    def create_zone(
        self,
        zone: Tuple[float, float, float, float],
        target_classes: Optional[List[int]] = None,
        min_score: float = 0.5,
    ) -> ZoneMonitor:
        """Create a Region-of-Interest monitor."""
        return ZoneMonitor(zone, target_classes=target_classes, min_score=min_score)

    def create_persistence_filter(
        self, required_consecutive_frames: int = 3, cooldown_frames: int = 15
    ) -> PersistenceFilter:
        """Create a debouncing filter for steady detections."""
        return PersistenceFilter(
            required_consecutive_frames=required_consecutive_frames,
            cooldown_frames=cooldown_frames,
        )

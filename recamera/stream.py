"""
RTSP Video and WebSocket Metadata dual-stream receiver.
"""

import json
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple
import cv2
import numpy as np
import websocket

from .drawing import draw_detections


class StreamReceiver:
    """Manages concurrent RTSP video stream and WebSocket metadata feed."""

    def __init__(
        self,
        camera_ip: str = "192.168.42.1",
        rtsp_port: int = 554,
        rtsp_path: str = "/live",
        rtsp_username: Optional[str] = "admin",
        rtsp_password: Optional[str] = "admin",
        ws_port: int = 1880,
        ws_path: str = "/ws/boxes",
        labels: Optional[List[str]] = None,
        on_detection: Optional[Callable[[List[Dict]], None]] = None,
    ):
        self.camera_ip = camera_ip
        if rtsp_username and rtsp_password:
            self.rtsp_url = f"rtsp://{rtsp_username}:{rtsp_password}@{camera_ip}:{rtsp_port}{rtsp_path}"
        else:
            self.rtsp_url = f"rtsp://{camera_ip}:{rtsp_port}{rtsp_path}"
        self.ws_url = f"ws://{camera_ip}:{ws_port}{ws_path}"
        self.labels = labels or []
        self.on_detection = on_detection

        self._latest_boxes: List[Dict] = []
        self._lock = threading.Lock()
        self._running = False
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_app: Optional[websocket.WebSocketApp] = None
        self._cap: Optional[cv2.VideoCapture] = None

    def _on_ws_message(self, ws, message: str) -> None:
        try:
            data = json.loads(message)
            boxes = data.get("boxes", []) if isinstance(data, dict) else data
            with self._lock:
                self._latest_boxes = boxes
            if self.on_detection:
                self.on_detection(boxes)
        except Exception:
            pass

    def _ws_worker(self) -> None:
        while self._running:
            try:
                self._ws_app = websocket.WebSocketApp(
                    self.ws_url,
                    on_message=self._on_ws_message,
                )
                self._ws_app.run_forever()
            except Exception:
                pass
            time.sleep(1.5)

    def start(self) -> bool:
        """Start WebSocket listener thread and connect to RTSP stream."""
        self._running = True
        self._ws_thread = threading.Thread(target=self._ws_worker, daemon=True)
        self._ws_thread.start()

        self._cap = cv2.VideoCapture(self.rtsp_url)
        return self._cap.isOpened()

    def get_latest_boxes(self) -> List[Dict]:
        """Fetch the latest bounding boxes in a thread-safe manner."""
        with self._lock:
            return list(self._latest_boxes)

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray], List[Dict]]:
        """Read the next video frame along with the latest detections."""
        if not self._cap or not self._cap.isOpened():
            return False, None, []
        ret, frame = self._cap.read()
        if not ret:
            return False, None, []
        return True, frame, self.get_latest_boxes()

    def draw(self, frame: np.ndarray, boxes: Optional[List[Dict]] = None) -> np.ndarray:
        """Draw detections onto a frame using configured labels."""
        b = boxes if boxes is not None else self.get_latest_boxes()
        return draw_detections(frame, b, self.labels)

    def snapshot(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Grab a single current video frame."""
        ret, frame, _ = self.read_frame()
        return ret, frame

    def stop(self) -> None:
        """Stop threads and release video capture."""
        self._running = False
        if self._ws_app:
            try:
                self._ws_app.close()
            except Exception:
                pass
        if self._cap:
            self._cap.release()
            self._cap = None

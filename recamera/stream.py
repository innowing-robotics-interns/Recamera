"""Concurrent RTSP video and websocket detection receiver."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

# Read by OpenCV's FFmpeg backend when a capture is opened.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;4000000|max_delay;500000"
)
# The camera's H.264 stream starts mid-GOP, so FFmpeg logs a burst of
# "non-existing PPS 0 referenced" before the first keyframe. That is normal,
# but it reads as an error, so keep it off the console.
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "8")

import contextlib

import cv2
import numpy as np
import websocket

from .detections import DEFAULT_PREVIEW, parse_message
from .drawing import draw_detections


class StreamReceiver:
    """Keeps the newest frame and newest detections available to readers.

    The detection feed is authoritative: when it carries a preview image the
    reader gets that image with matching coordinates, so boxes always line up
    even though RTSP is a different resolution (1920x1080 vs a 1280x720
    preview). RTSP is the fallback video source.
    """

    def __init__(
        self,
        camera_ip: str = "192.168.42.1",
        rtsp_port: int = 554,
        rtsp_path: str = "/live",
        rtsp_username: str | None = "admin",
        rtsp_password: str | None = "admin",
        ws_port: int = 1880,
        ws_path: str = "/ws/boxes",
        labels: list[str] | None = None,
        preview_size: tuple[int, int] = DEFAULT_PREVIEW,
        on_detection: Callable[[list[dict[str, Any]]], None] | None = None,
        rtsp: bool = True,
    ):
        self.camera_ip = camera_ip
        if rtsp_username and rtsp_password:
            self.rtsp_url = f"rtsp://{rtsp_username}:{rtsp_password}@{camera_ip}:{rtsp_port}{rtsp_path}"
        else:
            self.rtsp_url = f"rtsp://{camera_ip}:{rtsp_port}{rtsp_path}"
        self.ws_url = f"ws://{camera_ip}:{ws_port}{ws_path}"
        self.labels = labels or []
        self.preview_size = preview_size
        self.on_detection = on_detection
        self.use_rtsp = rtsp

        self._latest_boxes: list[dict[str, Any]] = []
        self._latest_frame: np.ndarray | None = None
        self._box_resolution: tuple[int, int] | None = None
        self._ws_messages = 0
        self._lock = threading.Lock()
        self._running = False
        self._ws_thread: threading.Thread | None = None
        self._ws_app: websocket.WebSocketApp | None = None
        self._cap: cv2.VideoCapture | None = None

    # -- websocket ----------------------------------------------------------

    def _on_ws_message(self, _ws, message) -> None:
        record = parse_message(message)
        frame = record["frame"]
        resolution = record["resolution"]
        with self._lock:
            self._latest_boxes = record["boxes"]
            self._ws_messages += 1
            if frame is not None:
                self._latest_frame = frame
                # a preview image is exactly resolution-sized
                self._box_resolution = resolution or (frame.shape[1], frame.shape[0])
            elif resolution is not None:
                self._box_resolution = resolution
        if record["labels"] and not self.labels:
            self.labels = record["labels"]
        if self.on_detection:
            self.on_detection(record["boxes"])

    def _ws_worker(self) -> None:
        while self._running:
            try:
                self._ws_app = websocket.WebSocketApp(self.ws_url, on_message=self._on_ws_message)
                self._ws_app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                pass
            time.sleep(1.5)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> bool:
        """Start the detection listener and, optionally, the RTSP reader."""
        self._running = True
        self._ws_thread = threading.Thread(target=self._ws_worker, daemon=True)
        self._ws_thread.start()
        if self.use_rtsp:
            self._open_rtsp()
        return True

    def _open_rtsp(self) -> None:
        deadline = time.time() + 4
        while time.time() < deadline:
            capture = cv2.VideoCapture()
            if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000)
            if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                capture.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4000)
            if capture.open(self.rtsp_url, cv2.CAP_FFMPEG) and capture.isOpened():
                self._cap = capture
                return
            capture.release()
            time.sleep(0.4)

    def stop(self) -> None:
        self._running = False
        if self._ws_app:
            with contextlib.suppress(Exception):
                self._ws_app.close()
        if self._cap:
            self._cap.release()
            self._cap = None

    # -- readers ------------------------------------------------------------

    @property
    def ws_messages(self) -> int:
        with self._lock:
            return self._ws_messages

    def get_latest_boxes(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._latest_boxes)

    def get_resolution(self) -> tuple[int, int] | None:
        """The pixel space of the current boxes."""
        with self._lock:
            return self._box_resolution

    def read_frame(self) -> tuple[bool, np.ndarray | None, list[dict[str, Any]]]:
        """Newest (frame, boxes); boxes are in the returned frame's pixel space."""
        with self._lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()
            boxes = list(self._latest_boxes)
            resolution = self._box_resolution
        if frame is not None:
            return True, frame, boxes

        if not self._cap or not self._cap.isOpened():
            return False, None, boxes
        ok, video = self._cap.read()
        if not ok:
            return False, None, boxes
        if resolution and (video.shape[1], video.shape[0]) != resolution:
            from .detections import scale_box

            boxes = [scale_box(box, (video.shape[1], video.shape[0]), resolution) for box in boxes]
        return True, video, boxes

    def draw(self, frame: np.ndarray, boxes: list[dict[str, Any]] | None = None) -> np.ndarray:
        return draw_detections(frame, boxes if boxes is not None else self.get_latest_boxes(), self.labels)

    def snapshot(self) -> tuple[bool, np.ndarray | None]:
        ok, frame, _ = self.read_frame()
        return ok, frame

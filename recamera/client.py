"""High-level client: one object for video, detections and the REST API."""

from __future__ import annotations

from typing import Any

import numpy as np

from .analytics import PersistenceFilter, ZoneMonitor
from .api import Supervisor
from .config import Config
from .detections import DEFAULT_PREVIEW
from .stream import StreamReceiver


class ReCamera:
    """Unified client for a Seeed Studio reCamera."""

    def __init__(
        self,
        camera_ip: str | None = None,
        labels: list[str] | None = None,
        rtsp_port: int | None = None,
        rtsp_path: str | None = None,
        rtsp_username: str | None = None,
        rtsp_password: str | None = None,
        ws_port: int | None = None,
        ws_path: str | None = None,
        api_port: int | None = None,
        preview_size: tuple[int, int] | None = None,
        rtsp: bool = True,
    ):
        config = Config.from_env()
        self.config = config
        self.camera_ip = camera_ip or config.camera_ip
        self.labels = labels or []

        self.api = Supervisor(camera_ip=self.camera_ip, port=api_port or config.api_port)
        self._stream = StreamReceiver(
            camera_ip=self.camera_ip,
            rtsp_port=rtsp_port or config.rtsp_port,
            rtsp_path=rtsp_path or config.rtsp_path,
            rtsp_username=config.rtsp_user if rtsp_username is None else rtsp_username,
            rtsp_password=config.rtsp_pass if rtsp_password is None else rtsp_password,
            ws_port=ws_port or config.ws_port,
            ws_path=ws_path or config.ws_path,
            labels=self.labels,
            preview_size=preview_size or config.preview_size or DEFAULT_PREVIEW,
            rtsp=rtsp,
        )

    def set_labels(self, labels: list[str]) -> None:
        """Replace the class labels used when drawing."""
        self.labels = list(labels)
        self._stream.labels = list(labels)

    @property
    def rtsp_url(self) -> str:
        return self._stream.rtsp_url

    @property
    def ws_url(self) -> str:
        return self._stream.ws_url

    def connect(self) -> bool:
        return self._stream.start()

    def disconnect(self) -> None:
        self._stream.stop()

    def __enter__(self) -> ReCamera:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    def read_frame(self) -> tuple[bool, np.ndarray | None, list[dict[str, Any]]]:
        return self._stream.read_frame()

    def draw(self, frame: np.ndarray, boxes: list[dict[str, Any]] | None = None) -> np.ndarray:
        return self._stream.draw(frame, boxes)

    def snapshot(self) -> tuple[bool, np.ndarray | None]:
        return self._stream.snapshot()

    @property
    def boxes(self) -> list[dict[str, Any]]:
        return self._stream.get_latest_boxes()

    @property
    def ws_messages(self) -> int:
        return self._stream.ws_messages

    def create_zone(
        self,
        zone: tuple[float, float, float, float],
        target_classes: list[int] | None = None,
        min_score: float = 0.5,
    ) -> ZoneMonitor:
        return ZoneMonitor(zone, target_classes=target_classes, min_score=min_score)

    def create_persistence_filter(
        self, required_consecutive_frames: int = 3, cooldown_frames: int = 15
    ) -> PersistenceFilter:
        return PersistenceFilter(
            required_consecutive_frames=required_consecutive_frames,
            cooldown_frames=cooldown_frames,
        )

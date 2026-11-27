"""Connection settings, resolved from arguments, the environment and ``.env``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import find_dotenv, load_dotenv

    # Look from the working directory upwards; ignore a missing file.
    load_dotenv(find_dotenv(usecwd=True))
except Exception:  # pragma: no cover - dotenv is optional at import time
    pass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass
class Config:
    camera_ip: str = "192.168.42.1"
    api_port: int = 80
    username: str = "recamera"
    password: str = "recamera"
    rtsp_port: int = 554
    rtsp_path: str = "/live"
    rtsp_user: str = "admin"
    rtsp_pass: str = "admin"
    ws_port: int = 1880
    ws_path: str = "/ws/boxes"
    nodered_port: int = 1880
    preview_width: int = 1280
    preview_height: int = 720

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            camera_ip=os.getenv("RECAMERA_IP", "192.168.42.1"),
            api_port=_env_int("RECAMERA_API_PORT", 80),
            username=os.getenv("RECAMERA_USERNAME", "recamera"),
            password=os.getenv("RECAMERA_PASSWORD", "recamera"),
            rtsp_port=_env_int("RECAMERA_RTSP_PORT", 554),
            rtsp_path=os.getenv("RECAMERA_RTSP_PATH", "/live"),
            rtsp_user=os.getenv("RECAMERA_RTSP_USER", "admin"),
            rtsp_pass=os.getenv("RECAMERA_RTSP_PASS", "admin"),
            ws_port=_env_int("RECAMERA_WS_PORT", 1880),
            ws_path=os.getenv("RECAMERA_WS_PATH", "/ws/boxes"),
            nodered_port=_env_int("RECAMERA_NODERED_PORT", 1880),
            preview_width=_env_int("RECAMERA_PREVIEW_WIDTH", 1280),
            preview_height=_env_int("RECAMERA_PREVIEW_HEIGHT", 720),
        )

    @property
    def preview_size(self) -> tuple[int, int]:
        return self.preview_width, self.preview_height


def default_models_dir() -> Path:
    return Path(os.getenv("RECAMERA_MODELS_DIR") or Path(__file__).resolve().parent.parent / "models")


def default_backup_dir() -> Path:
    return Path(os.getenv("RECAMERA_BACKUP_DIR") or Path(__file__).resolve().parent.parent / "backups")

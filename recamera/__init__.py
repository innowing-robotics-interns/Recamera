"""
recamera - Python SDK for Seeed Studio reCamera (SG2002 / cv181x)
"""

from .analytics import PersistenceFilter, ZoneMonitor
from .api import ReCameraAPI
from .client import ReCamera
from .drawing import draw_detections
from .stream import StreamReceiver

__version__ = "0.1.0"

__all__ = [
    "ReCamera",
    "StreamReceiver",
    "ReCameraAPI",
    "ZoneMonitor",
    "PersistenceFilter",
    "draw_detections",
]

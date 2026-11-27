"""recamera - Python SDK and deployment tool for Seeed Studio reCameras (SG2002 / cv181x)."""

from .analytics import PersistenceFilter, ZoneMonitor
from .api import ReCameraAPI, Supervisor
from .client import ReCamera
from .config import Config
from .detections import normalise_box, normalise_score, parse_message
from .drawing import draw_detections
from .errors import DeviceError, ManifestError, ReCameraError
from .manifest import Bundle, ModelManifest, load_bundle, load_manifest
from .nodered import NodeRed, flow_matches, patch_model_nodes
from .stream import StreamReceiver

__version__ = "0.2.0"

__all__ = [
    "Bundle",
    "Config",
    "DeviceError",
    "ManifestError",
    "ModelManifest",
    "NodeRed",
    "PersistenceFilter",
    "ReCamera",
    "ReCameraAPI",
    "ReCameraError",
    "StreamReceiver",
    "Supervisor",
    "ZoneMonitor",
    "__version__",
    "draw_detections",
    "flow_matches",
    "load_bundle",
    "load_manifest",
    "normalise_box",
    "normalise_score",
    "parse_message",
    "patch_model_nodes",
]

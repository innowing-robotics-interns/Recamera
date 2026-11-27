"""Node-RED admin API client (port 1880) and model-node patching."""

from __future__ import annotations

import time
from typing import Any

import requests

from .errors import DeviceError
from .manifest import ModelManifest

HEADERS = {"Node-RED-API-Version": "v2"}


class NodeRed:
    """Talks to the Node-RED admin API on ``http://<ip>:1880``."""

    def __init__(self, camera_ip: str = "192.168.42.1", port: int = 1880, timeout: float = 15.0):
        self.camera_ip = camera_ip
        self.base_url = f"http://{camera_ip}:{port}"
        self.timeout = timeout
        self.session = requests.Session()

    def _request(self, method: str, path: str, *, timeout: float | None = None, **kwargs) -> Any:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                headers=HEADERS,
                timeout=timeout or self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise DeviceError(f"Node-RED unreachable at {self.base_url}") from exc
        if response.status_code not in (200, 204):
            raise DeviceError(f"{method.upper()} :1880/{path} -> HTTP {response.status_code}")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise DeviceError(f":1880/{path} returned non-JSON") from exc

    def state(self) -> str:
        try:
            data = self._request("get", "flows/state", timeout=5)
        except DeviceError:
            return ""
        return (data or {}).get("state", "")

    def set_state(self, state: str) -> None:
        self._request("post", "flows/state", json={"state": state}, timeout=10)

    def get_flows(self) -> tuple[list[dict], str | None]:
        data = self._request("get", "flows")
        if isinstance(data, dict):
            return data.get("flows", []), data.get("rev")
        return data or [], None

    def deploy(self, flows: list[dict]) -> str | None:
        data = self._request("post", "flows", json={"flows": flows}, timeout=30)
        return (data or {}).get("rev")

    def model_nodes(self, flows: list[dict]) -> list[dict]:
        return [node for node in flows if node.get("type") == "model"]

    def wait_until_running(self, timeout: float = 300, settle: int = 8, min_wait: float = 0) -> bool:
        """Wait until the flow is started and stays started for ``settle`` polls."""
        started = time.time()
        good = 0
        while time.time() - started < timeout:
            time.sleep(1)
            if time.time() - started < min_wait:
                continue
            good = good + 1 if self.state() == "start" else 0
            if good >= settle:
                return True
        return False


def patch_model_nodes(flows: list[dict], manifest: ModelManifest) -> int:
    """Point every ``model`` node at ``manifest``; return how many were patched.

    ``uri=""`` makes the node use the model the supervisor is serving, which is
    exactly what was just uploaded. Labels must be in training order.
    """
    patched = 0
    for node in flows:
        if node.get("type") != "model":
            continue
        node["classes"] = manifest.class_labels
        node["uri"] = ""
        node["model"] = manifest.flow_name
        node["tscore"] = float(manifest.score)
        node["tiou"] = float(manifest.iou)
        patched += 1
    return patched


def flow_matches(flows: list[dict], manifest: ModelManifest) -> bool:
    """True when every model node already reflects ``manifest``."""
    nodes = [n for n in flows if n.get("type") == "model"]
    if not nodes:
        return False
    return all(
        str(n.get("classes", "")) == manifest.class_labels
        and str(n.get("model", "")) == manifest.flow_name
        for n in nodes
    )

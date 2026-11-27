"""Supervisor REST client for the reCamera's management service (port 80).

Only a few endpoints need a login; the model read endpoints are open on the
local network. ``Supervisor.login()`` is therefore optional for the common
deploy path but required for upload on some firmware builds.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from typing import Any

import requests

from .errors import DeviceError
from .manifest import ModelManifest, manifest_from_dict, md5_bytes

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    _LOGIN_KEY = b"zqCwT7H7!rNdP3wL"  # firmware 0.2.x web UI key
    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover - optional dependency
    _HAS_CRYPTO = False

UPLOAD_CHUNK = 512 * 1024  # the camera's own web UI uses 512 KiB chunks
RUNNING = 0
SERVICE_NAMES = {0: "running", 1: "starting", 2: "failed", 4: "error"}


def encrypt_password(password: str) -> str:
    """The supervisor expects the password AES-ECB encrypted, zero padded."""
    if not _HAS_CRYPTO:
        return password
    data = password.encode("utf-8")
    data += b"\x00" * ((16 - len(data) % 16) % 16)
    encryptor = Cipher(algorithms.AES(_LOGIN_KEY), modes.ECB()).encryptor()
    return (encryptor.update(data) + encryptor.finalize()).hex()


class Supervisor:
    """Minimal client for ``http://<ip>/api`` on a reCamera."""

    def __init__(
        self,
        camera_ip: str = "192.168.42.1",
        port: int = 80,
        token: str | None = None,
        timeout: float = 10.0,
    ):
        self.camera_ip = camera_ip
        self.base_url = f"http://{camera_ip}:{port}/api"
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()

    # -- plumbing -----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    def request(self, method: str, path: str, *, timeout: float | None = None, **kwargs) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.request(
                method,
                url,
                headers=kwargs.pop("headers", self._headers()),
                timeout=timeout or self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise DeviceError(f"cannot reach {self.camera_ip} ({exc.__class__.__name__})") from exc
        if response.status_code != 200:
            raise DeviceError(f"{method.upper()} /api/{path} -> HTTP {response.status_code}")
        return response

    def call(self, method: str, path: str, *, timeout: float | None = None, **kwargs) -> Any:
        """Call an endpoint and return the ``data`` field, checking ``code``."""
        response = self.request(method, path, timeout=timeout, **kwargs)
        try:
            body = response.json()
        except ValueError as exc:
            raise DeviceError(f"/api/{path} returned non-JSON") from exc
        if isinstance(body, dict) and body.get("code") not in (0, "0", None):
            raise DeviceError(f"/api/{path} failed: {body.get('msg') or body}")
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    # -- session ------------------------------------------------------------

    def login(self, username: str = "recamera", password: str = "recamera") -> bool:
        """Authenticate and store the bearer token. Returns False on bad credentials."""
        try:
            response = self.session.post(
                f"{self.base_url}/userMgr/login",
                json={"userName": username, "password": encrypt_password(password)},
                timeout=8,
            )
        except requests.RequestException:
            return False
        if response.status_code != 200:
            return False
        try:
            body = response.json()
        except ValueError:
            return False
        token = (body.get("data") or {}).get("token")
        if body.get("code") == 0 and token:
            self.token = token
            return True
        return False

    # -- device -------------------------------------------------------------

    def version(self) -> str:
        try:
            return str(self.call("get", "version", timeout=5) or "")
        except DeviceError:
            return ""

    def device_info(self) -> dict[str, Any]:
        try:
            return self.call("get", "deviceMgr/queryDeviceInfo", timeout=8) or {}
        except DeviceError:
            return {}

    def service_status(self) -> dict[str, int]:
        try:
            return self.call("get", "deviceMgr/queryServiceStatus", timeout=5) or {}
        except DeviceError:
            return {}

    def services_running(self) -> bool:
        status = self.service_status()
        return all(status.get(key) == RUNNING for key in ("nodeRed", "sscmaNode", "system"))

    # -- models -------------------------------------------------------------

    def model_info(self) -> ModelManifest:
        """The manifest of the model the camera currently serves."""
        data = self.call("get", "deviceMgr/getModelInfo", timeout=8) or {}
        if not isinstance(data, dict):
            raise DeviceError("camera returned unexpected model_info data")
        raw = data.get("model_info", data)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise DeviceError(f"camera returned unparseable model_info: {exc}") from exc
        if not isinstance(raw, dict):
            raise DeviceError("camera returned no model_info")
        return manifest_from_dict(raw)

    def model_file(self, timeout: float = 120) -> bytes:
        """The compiled model currently served, as bytes."""
        return self.request("get", "deviceMgr/getModelFile", timeout=timeout).content

    def model_list(self) -> list[dict[str, Any]]:
        try:
            data = self.call("get", "deviceMgr/getModelList", timeout=10) or {}
        except DeviceError:
            return []
        if isinstance(data, dict):
            data = data.get("list", [])
        return data if isinstance(data, list) else []

    def upload_model(
        self,
        data: bytes,
        manifest: ModelManifest,
        progress: Callable[[float], None] | None = None,
    ) -> None:
        """Upload a compiled model in 512 KiB chunks.

        ``model_info`` is attached to the final chunk, which is what tells the
        supervisor the name and class list to record in ``model.json``.
        """
        total = len(data)
        if total == 0:
            raise DeviceError("refusing to upload an empty model")
        model_info = json.dumps(manifest.to_payload())
        for offset in range(0, total, UPLOAD_CHUNK):
            chunk = data[offset : offset + UPLOAD_CHUNK]
            fields = {"offset": str(offset), "size": str(total)}
            if offset + UPLOAD_CHUNK >= total:
                fields["model_info"] = model_info
            self._upload_chunk(chunk, fields)
            if progress:
                progress(min(100.0, (offset + len(chunk)) / total * 100))

    def _upload_chunk(self, chunk: bytes, fields: dict[str, str]) -> None:
        url = f"{self.base_url}/deviceMgr/uploadModel"
        headers = {"Authorization": self.token} if self.token else {}
        last: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.post(
                    url,
                    files={"model_file": ("model.cvimodel", chunk, "application/octet-stream")},
                    data=fields,
                    headers=headers,
                    timeout=120,
                )
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if response.status_code == 200 and body.get("code") in (0, "0"):
                    return
                last = DeviceError(
                    f"upload chunk at offset {fields['offset']} rejected: "
                    f"HTTP {response.status_code} {body.get('msg') or ''}".strip()
                )
            except requests.RequestException as exc:
                last = DeviceError(
                    f"upload chunk at offset {fields['offset']} failed: {exc.__class__.__name__}"
                )
            if attempt < 2:
                time.sleep(2)
        raise last or DeviceError("upload failed")

    def wait_for_model_file(self, expected_md5: str, timeout: float = 120) -> bool:
        """Poll until the served model file hashes to ``expected_md5``."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if md5_bytes(self.model_file(timeout=60)) == expected_md5:
                    return True
            except DeviceError:
                pass
            time.sleep(2)
        return False


# Backwards-compatible name for code written against the 0.1 SDK.
ReCameraAPI = Supervisor


def iter_chunks(data: bytes, size: int = UPLOAD_CHUNK) -> Iterable[bytes]:
    for offset in range(0, len(data), size):
        yield data[offset : offset + size]

"""The supervisor client must match the camera's upload contract exactly."""

import json

import pytest
import requests

from recamera.api import UPLOAD_CHUNK, Supervisor, encrypt_password
from recamera.errors import DeviceError
from recamera.manifest import ModelManifest


class FakeResponse:
    def __init__(self, status_code=200, body=None, content=b""):
        self.status_code = status_code
        self._body = body if body is not None else {"code": 0, "data": {}, "msg": "OK"}
        self.content = content
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class RecordingSession:
    """Stands in for requests.Session and records every call."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self._responses:
            return self._responses.pop(0)
        return FakeResponse()

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def make_supervisor() -> Supervisor:
    client = Supervisor(camera_ip="10.0.0.5")
    client.session = RecordingSession()
    return client


def manifest(classes=("screw", "nut")) -> ModelManifest:
    return ModelManifest(model_id="1", model_name="demo.onnx", classes=list(classes))


def test_password_encryption_is_deterministic_and_zero_padded():
    # "recamera" is 8 bytes -> one AES block -> 16 bytes -> 32 hex characters.
    encrypted = encrypt_password("recamera")
    assert len(encrypted) == 32
    assert encrypted == encrypt_password("recamera")
    assert encrypt_password("a") != encrypt_password("b")
    # CryptoJS-style ZeroPadding does not add a block when already aligned:
    # a 16-byte password is still a single block.
    assert len(encrypt_password("0123456789abcdef")) == 32
    # 17 bytes spills into two blocks
    assert len(encrypt_password("0123456789abcdefg")) == 64


def test_small_model_uploads_in_one_chunk_with_model_info():
    client = make_supervisor()
    client.upload_model(b"CviModel" + b"x" * 100, manifest())
    assert len(client.session.calls) == 1
    call = client.session.calls[0]
    assert call["url"].endswith("/api/deviceMgr/uploadModel")
    assert set(call["files"]) == {"model_file"}
    assert call["data"]["offset"] == "0"
    assert call["data"]["size"] == "108"
    payload = json.loads(call["data"]["model_info"])
    assert payload["classes"] == ["screw", "nut"]
    assert payload["flow_name"] == "demo"


def test_large_model_is_chunked_at_512_kib():
    client = make_supervisor()
    data = b"CviModel" + b"\0" * (UPLOAD_CHUNK * 2 + 10)
    client.upload_model(data, manifest())
    calls = client.session.calls
    assert len(calls) == 3
    assert [c["data"]["offset"] for c in calls] == ["0", str(UPLOAD_CHUNK), str(UPLOAD_CHUNK * 2)]
    # model_info rides only on the final chunk
    assert "model_info" not in calls[0]["data"]
    assert "model_info" not in calls[1]["data"]
    assert "model_info" in calls[2]["data"]
    total = sum(len(c["files"]["model_file"][1]) for c in calls)
    assert total == len(data)


def test_upload_progress_reaches_100():
    client = make_supervisor()
    seen = []
    client.upload_model(b"CviModel" + b"\0" * (UPLOAD_CHUNK * 2), manifest(), progress=seen.append)
    assert seen[-1] == 100.0
    assert seen == sorted(seen)


def test_upload_retries_a_failed_chunk(monkeypatch):
    client = make_supervisor()
    client.session = RecordingSession(
        [FakeResponse(500, {"code": -1, "msg": "busy"}), FakeResponse()]
    )
    monkeypatch.setattr("time.sleep", lambda _s: None)
    client.upload_model(b"CviModel" + b"x", manifest())
    assert len(client.session.calls) == 2


def test_upload_gives_up_after_three_attempts(monkeypatch):
    client = make_supervisor()
    client.session = RecordingSession([FakeResponse(500, {"code": -1, "msg": "busy"})] * 3)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(DeviceError, match="offset 0"):
        client.upload_model(b"CviModelx", manifest())


def test_empty_model_is_refused():
    client = make_supervisor()
    with pytest.raises(DeviceError, match="empty"):
        client.upload_model(b"", manifest())


def test_model_info_parses_both_string_and_object():
    client = make_supervisor()
    as_string = {"model_id": "1", "model_name": "m", "classes": ["a"]}
    client.session = RecordingSession(
        [FakeResponse(body={"code": 0, "data": {"model_info": json.dumps(as_string)}})]
    )
    assert client.model_info().classes == ["a"]

    as_object = {"model_id": "1", "model_name": "m", "classes": ["b"]}
    client.session = RecordingSession(
        [FakeResponse(body={"code": 0, "data": {"model_info": as_object}})]
    )
    assert client.model_info().classes == ["b"]


def test_service_error_raises_device_error():
    client = make_supervisor()
    client.session = RecordingSession([FakeResponse(body={"code": -1, "msg": "nope"})])
    with pytest.raises(DeviceError, match="nope"):
        client.call("get", "whatever")


def test_connection_errors_are_wrapped():
    client = Supervisor(camera_ip="10.255.255.1")

    class Boom:
        def request(self, *a, **k):
            raise requests.ConnectionError("down")

    client.session = Boom()
    with pytest.raises(DeviceError, match="cannot reach"):
        client.call("get", "version")

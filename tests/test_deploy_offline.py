"""The deploy sequence, driven end-to-end against a fake camera.

These tests do not touch a real device. They pin down the order of operations:
health check -> backup -> (conditional) upload -> flow patch -> verification.
"""

import json
from pathlib import Path

import pytest

from recamera.api import Supervisor
from recamera.config import Config
from recamera.deploy import Deployer
from recamera.errors import DeviceError
from recamera.manifest import ModelManifest, md5_bytes
from recamera.nodered import NodeRed


class FakeApi(Supervisor):
    """In-memory stand-in for the supervisor service."""

    def __init__(self, model_bytes: bytes, manifest: ModelManifest):
        super().__init__(camera_ip="10.0.0.1")
        self._model_bytes = model_bytes
        self._manifest = manifest
        self.services_up = True
        self.uploads = []

    def device_info(self):
        return {"deviceName": "fake", "osVersion": "0.2.4", "ip": "10.0.0.1"}

    def service_status(self):
        return {"nodeRed": 0 if self.services_up else 2, "sscmaNode": 0, "system": 0}

    def services_running(self):
        return self.services_up

    def model_info(self):
        return self._manifest

    def model_file(self, timeout: float = 120) -> bytes:
        return self._model_bytes

    def upload_model(self, data, manifest, progress=None):
        self.uploads.append((len(data), manifest.flow_name))
        self._model_bytes = data
        self._manifest = manifest
        if progress:
            progress(100.0)

    def wait_for_model_file(self, expected_md5, timeout=120):
        return md5_bytes(self._model_bytes) == expected_md5


class FakeNodeRed(NodeRed):
    def __init__(self, flow):
        super().__init__(camera_ip="10.0.0.1")
        self.flow = flow
        self.deploys = 0
        self.state_value = "start"

    def state(self):
        return self.state_value

    def get_flows(self):
        return json.loads(json.dumps(self.flow)), "rev1"

    def deploy(self, flows):
        self.flow = flows
        self.deploys += 1
        return "rev2"


def build(tmp_path: Path, api_bytes: bytes, manifest: ModelManifest, flow):
    deployer = Deployer(
        config=Config(camera_ip="10.0.0.1"), backup_dir=tmp_path / "backups", log=lambda _m: None
    )
    fake_api = FakeApi(api_bytes, manifest)
    fake_nr = FakeNodeRed(flow)
    deployer.api = fake_api
    deployer.nodered = fake_nr
    deployer.wait_until_ready = lambda timeout=300, min_wait=0, settle=8: True
    deployer.check_live = lambda seconds=8, ws_port=None: 5
    deployer._backup_impl = deployer.backup
    deployed = []

    def fake_backup(note="", kind="", quiet=False):
        deployed.append(note)
        return tmp_path / "backups" / "fake"

    deployer.backup = fake_backup
    return deployer, fake_api, fake_nr


FLOW = [
    {"type": "model", "id": "m", "model": "old", "classes": "", "uri": "/x", "tscore": 0.9, "tiou": 0.9},
    {"type": "function", "id": "f", "func": "return msg;"},
]


def test_deploy_uploads_when_hash_differs(model_folder: Path, tmp_path: Path):
    from recamera.manifest import load_bundle

    manifest = load_bundle(model_folder).manifest
    deployer, api, nr = build(tmp_path, b"CviModelold", manifest, json.loads(json.dumps(FLOW)))
    result = deployer.deploy(model_folder)
    assert result.ok
    assert result.uploaded
    assert len(api.uploads) == 1
    assert nr.deploys == 1
    assert nr.flow[0]["classes"] == "screw,nut"
    assert nr.flow[0]["uri"] == ""


def test_deploy_skips_upload_when_hash_matches(model_folder: Path, tmp_path: Path):
    from recamera.manifest import load_bundle

    bundle = load_bundle(model_folder)
    deployer, api, nr = build(tmp_path, bundle.read_model(), bundle.manifest, json.loads(json.dumps(FLOW)))
    result = deployer.deploy(model_folder)
    assert result.ok
    assert not result.uploaded
    assert api.uploads == []
    assert nr.deploys == 1


def test_force_uploads_even_when_hash_matches(model_folder: Path, tmp_path: Path):
    from recamera.manifest import load_bundle

    bundle = load_bundle(model_folder)
    deployer, api, _nr = build(tmp_path, bundle.read_model(), bundle.manifest, json.loads(json.dumps(FLOW)))
    result = deployer.deploy(model_folder, force=True)
    assert result.uploaded
    assert len(api.uploads) == 1


def test_backup_is_taken_before_upload(model_folder: Path, tmp_path: Path):
    deployer, _api, _nr = build(
        tmp_path, b"CviModelold", ModelManifest("1", "m", ["a"]), json.loads(json.dumps(FLOW))
    )
    calls = []
    deployer.backup = lambda note="", kind="", quiet=False: calls.append("backup")
    original_upload = deployer.api.upload_model
    deployer.api.upload_model = lambda *a, **k: calls.append("upload") or original_upload(*a, **k)
    deployer.deploy(model_folder)
    assert calls[:2] == ["backup", "upload"]


def test_no_model_node_is_a_hard_error(model_folder: Path, tmp_path: Path):
    deployer, _api, _nr = build(tmp_path, b"CviModelold", ModelManifest("1", "m", ["a"]), [{"type": "tab"}])
    with pytest.raises(DeviceError, match="no 'model' node"):
        deployer.deploy(model_folder)


def test_no_backup_flag_skips_the_backup(model_folder: Path, tmp_path: Path):
    deployer, _api, _nr = build(
        tmp_path, b"CviModelold", ModelManifest("1", "m", ["a"]), json.loads(json.dumps(FLOW))
    )
    deployer.backup = lambda *a, **k: pytest.fail("backup should have been skipped")
    deployer.deploy(model_folder, no_backup=True)


def test_no_live_flag_skips_the_websocket_check(model_folder: Path, tmp_path: Path):
    deployer, _api, _nr = build(
        tmp_path, b"CviModelold", ModelManifest("1", "m", ["a"]), json.loads(json.dumps(FLOW))
    )
    deployer.check_live = lambda *a, **k: pytest.fail("live check should have been skipped")
    deployer.deploy(model_folder, no_live=True)


def test_warning_when_no_websocket_messages(model_folder: Path, tmp_path: Path):
    deployer, _api, _nr = build(
        tmp_path, b"CviModelold", ModelManifest("1", "m", ["a"]), json.loads(json.dumps(FLOW))
    )
    deployer.check_live = lambda *a, **k: 0
    result = deployer.deploy(model_folder)
    assert not result.ok
    assert any("no messages" in w for w in result.warnings)


def test_restore_reuploads_and_redeploys(model_folder: Path, tmp_path: Path):
    from recamera.manifest import load_bundle

    bundle = load_bundle(model_folder)
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "model.cvimodel").write_bytes(bundle.read_model())
    (backup / "model_info.json").write_text(bundle.manifest.to_json())
    (backup / "flows.json").write_text(json.dumps({"flows": FLOW}))

    deployer, api, nr  = build(
        tmp_path, b"CviModelold", ModelManifest("1", "m", ["a"]), json.loads(json.dumps(FLOW))
    )
    result = deployer.restore(backup, no_backup=True)
    assert result.ok and result.uploaded
    assert len(api.uploads) == 1
    assert nr.deploys == 1


def test_backup_failure_aborts_unless_disabled(model_folder: Path, tmp_path: Path, monkeypatch):
    from recamera.errors import ReCameraError

    deployer, _api, _nr = build(
        tmp_path, b"CviModelold", ModelManifest("1", "m", ["a"]), json.loads(json.dumps(FLOW))
    )

    def broken_backup(*args, **kwargs):
        raise ReCameraError("disk full")

    deployer.backup = broken_backup
    with pytest.raises(DeviceError, match="could not back up"):
        deployer.deploy(model_folder)
    # with the backup explicitly waived, the deploy proceeds
    result = deployer.deploy(model_folder, no_backup=True)
    assert result.ok


def test_restore_requires_services_before_touching_the_device(tmp_path: Path, model_folder: Path):
    deployer, api, _nr = build(
        tmp_path, b"CviModelold", ModelManifest("1", "m", ["a"]), json.loads(json.dumps(FLOW))
    )
    api.services_up = False
    deployer.wait_until_ready = lambda *a, **k: False
    with pytest.raises(DeviceError, match="not running"):
        deployer.restore(model_folder, no_backup=True)


def test_restore_without_backups_fails_clearly(tmp_path: Path):
    deployer = Deployer(config=Config(), backup_dir=tmp_path / "empty", log=lambda _m: None)
    with pytest.raises(Exception, match="no backups found"):
        deployer.restore(None)

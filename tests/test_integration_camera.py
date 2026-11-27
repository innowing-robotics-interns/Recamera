"""End-to-end tests against a real reCamera.

Skipped unless ``RECAMERA_INTEGRATION=1``. They change the model on the camera
(each step backs up first and the suite restores the original at the end), so
point them at a camera you can afford to modify.

    RECAMERA_INTEGRATION=1 uv run --extra test pytest tests/test_integration_camera.py
"""

from __future__ import annotations

import os
import time

import pytest

from recamera.api import Supervisor
from recamera.config import Config, default_backup_dir, default_models_dir
from recamera.deploy import Deployer
from recamera.detections import parse_message
from recamera.manifest import load_bundle, md5_bytes
from recamera.nodered import NodeRed, flow_matches

pytestmark = pytest.mark.skipif(
    os.getenv("RECAMERA_INTEGRATION") != "1",
    reason="set RECAMERA_INTEGRATION=1 to run tests against a real camera",
)


@pytest.fixture(scope="module")
def config() -> Config:
    return Config.from_env()


@pytest.fixture(scope="module")
def api(config: Config) -> Supervisor:
    client = Supervisor(camera_ip=config.camera_ip, port=config.api_port)
    if not client.device_info():
        pytest.skip(f"no camera reachable at {config.camera_ip}")
    return client


@pytest.fixture(scope="module")
def deployer(config: Config) -> Deployer:
    return Deployer(config=config)


def test_device_reports_firmware(api: Supervisor):
    info = api.device_info()
    assert info.get("deviceName") == "reCamera"
    assert info.get("osVersion")


def test_services_are_running(api: Supervisor):
    assert api.services_running(), "Node-RED/SSCMA are not running"


def test_flow_has_a_model_node(api: Supervisor, config: Config):
    flows, _ = NodeRed(camera_ip=config.camera_ip).get_flows()
    nodes = [n for n in flows if n.get("type") == "model"]
    assert nodes, "the flow has no model node"


def test_model_info_is_complete(api: Supervisor):
    manifest = api.model_info()
    assert manifest.model_name
    assert manifest.classes
    assert 0.0 <= manifest.score <= 1.0
    assert 0.0 <= manifest.iou <= 1.0


def test_websocket_publishes_normalised_boxes(deployer: Deployer):
    import threading

    import websocket

    records = []
    lock = threading.Lock()

    def on_message(_ws, message):
        with lock:
            records.append(parse_message(message))

    app = websocket.WebSocketApp(deployer._ws_url(), on_message=on_message)
    thread = threading.Thread(target=app.run_forever, daemon=True)
    thread.start()
    time.sleep(6)
    app.close()

    assert records, "no messages on /ws/boxes"
    boxes = [box for record in records for box in record["boxes"]]
    if not boxes:
        pytest.skip("camera is running but nothing is in view")
    for box in boxes:
        assert 0.0 <= box["score"] <= 1.0, f"score out of range: {box['score']}"
        assert box["w"] > 0 and box["h"] > 0


def test_full_deploy_cycle(config: Config, api: Supervisor, deployer: Deployer):
    """stock -> screw-nut -> original backup, asserting the device each time."""
    models = default_models_dir()
    screw = models / "screw-nut"
    stock = models / "yolo11n-detection"
    if not (screw / "model.cvimodel").exists() or not (stock / "model.cvimodel").exists():
        pytest.skip("bundled models are missing")

    original_md5 = md5_bytes(api.model_file())
    original_manifest = api.model_info()
    nodered = NodeRed(camera_ip=config.camera_ip)

    try:
        result = deployer.deploy(stock, force=True, no_live=True, timeout=600)
        assert result.ok, result.warnings
        assert md5_bytes(api.model_file()) == load_bundle(stock).md5
        assert api.model_info().flow_name == "yolo11n"
        assert flow_matches(nodered.get_flows()[0], load_bundle(stock).manifest)

        result = deployer.deploy(screw, force=True, no_live=True, timeout=600)
        assert result.ok, result.warnings
        assert md5_bytes(api.model_file()) == load_bundle(screw).md5
        assert api.model_info().flow_name == "yolo11n-aabb-screw-nut"
        assert flow_matches(nodered.get_flows()[0], load_bundle(screw).manifest)
    finally:
        # Put back exactly what was there before the test.
        if md5_bytes(api.model_file()) != original_md5:
            # The pre-deploy backups taken by deploy() include the original.
            restore_from = None
            for folder in sorted(default_backup_dir().iterdir(), reverse=True):
                meta = folder / "meta.json"
                if meta.exists() and original_md5 in meta.read_text():
                    restore_from = folder
                    break
            if restore_from is not None:
                deployer.restore(restore_from, no_backup=True, timeout=600)
            else:
                deployer.restore(deployer.latest_backup(), no_backup=True, timeout=600)

        assert md5_bytes(api.model_file()) == original_md5, "failed to restore the original model"
        assert api.model_info().flow_name == original_manifest.flow_name


def test_backup_round_trip(config: Config, api: Supervisor, deployer: Deployer):
    folder = deployer.backup(note="integration test", quiet=True)
    assert (folder / "model.cvimodel").exists()
    assert (folder / "model_info.json").exists()
    assert (folder / "meta.json").exists()
    assert md5_bytes((folder / "model.cvimodel").read_bytes()) == md5_bytes(api.model_file())


def test_backups_dir_is_populated(deployer: Deployer):
    assert default_backup_dir().exists()
    assert deployer.latest_backup() is not None

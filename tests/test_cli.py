"""The command line surface: parsing, validation and exit codes."""

import json
from pathlib import Path

import pytest

from recamera.cli import main


def run(argv):
    return main(argv)


def test_validate_accepts_a_good_folder(model_folder: Path, capsys):
    assert run(["validate", str(model_folder)]) == 0
    out = capsys.readouterr().out
    assert "is valid" in out
    assert "screw, nut" in out


def test_validate_rejects_a_bad_folder(tmp_path: Path, capsys):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "model.cvimodel").write_bytes(b"garbage")
    manifest = {"model_id": "1", "model_name": "x", "classes": ["a"]}
    (folder / "model_info.json").write_text(json.dumps(manifest))
    assert run(["validate", str(folder)]) == 2
    assert "not a compiled cvimodel" in capsys.readouterr().err


def test_list_shows_bundled_models(models_dir: Path, capsys):
    assert run(["list"]) == 0
    out = capsys.readouterr().out
    assert "screw-nut" in out
    assert "yolo11n-detection" in out


def test_list_json_is_parseable(models_dir: Path, capsys):
    assert run(["--json", "list"]) == 0
    data = json.loads(capsys.readouterr().out)
    names = {item["folder"] for item in data}
    assert {"screw-nut", "yolo11n-detection"} <= names
    for item in data:
        assert len(item["md5"]) == 32


def test_validate_override_rejects_out_of_range_score(model_folder: Path, capsys, monkeypatch):
    # deploy validates overrides before touching the network
    assert run(["deploy", str(model_folder), "--score", "2"]) == 2
    assert "score must be between" in capsys.readouterr().err


def test_deploy_override_labels_are_validated(model_folder: Path, capsys):
    assert run(["deploy", str(model_folder), "--labels", "a,b"]) == 2
    assert "commas" in capsys.readouterr().err


def test_unknown_command_errors():
    with pytest.raises(SystemExit) as exc:
        run(["nonsense"])
    assert exc.value.code == 2


def test_status_json_shape(capsys, monkeypatch):
    """status --json emits a stable schema even when the camera is unreachable."""
    from recamera import cli

    class Unreachable:
        camera_ip = "10.255.255.1"

        def device_info(self):
            return {}

        def service_status(self):
            return {}

        def services_running(self):
            return False

        def model_info(self):
            from recamera.errors import DeviceError

            raise DeviceError("down")

    class NoFlows:
        def get_flows(self):
            from recamera.errors import DeviceError

            raise DeviceError("down")

        def model_nodes(self, flows):
            return []

    class FakeDeployer:
        api = Unreachable()
        nodered = NoFlows()

    monkeypatch.setattr(cli, "_deployer", lambda args: FakeDeployer())
    assert run(["--json", "status", "--ip", "10.255.255.1"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"device", "services", "model", "model_error", "flow"}
    assert payload["model"] is None
    assert payload["model_error"]

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _write_model(path: Path, payload: bytes = b"model-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"CviModel" + payload)
    return path


@pytest.fixture
def model_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "demo"
    _write_model(folder / "model.cvimodel")
    (folder / "model_info.json").write_text(
        json.dumps(
            {
                "model_id": "42",
                "model_name": "demo.onnx",
                "flow_name": "demo",
                "classes": ["screw", "nut"],
                "thresholds": {"score": 0.5, "iou": 0.4},
            }
        )
    )
    return folder


@pytest.fixture
def models_dir() -> Path:
    return REPO / "models"

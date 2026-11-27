"""The models shipped in this repo must be deployable as-is."""

from pathlib import Path

import pytest

from recamera.manifest import load_bundle, md5_file

EXPECTED = {
    "screw-nut": {
        "md5": "34427e072595bc09fef6489db973cfad",
        "classes": ["screw", "nut"],
        "flow_name": "yolo11n-aabb-screw-nut",
    },
    "yolo11n-detection": {
        # the bytes the firmware actually ships, not a re-conversion
        "md5": "7819bd8d3958f5184fb20cd8b0490525",
        "classes": None,
        "flow_name": "yolo11n",
    },
}


def test_expected_models_are_present(models_dir: Path):
    folders = {p.name for p in models_dir.iterdir() if p.is_dir()}
    assert set(EXPECTED) <= folders


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_bundled_model_matches_its_manifest(models_dir: Path, name: str):
    bundle = load_bundle(models_dir / name)
    expected = EXPECTED[name]
    assert bundle.md5 == expected["md5"]
    assert bundle.manifest.flow_name == expected["flow_name"]
    if expected["classes"] is not None:
        assert bundle.manifest.classes == expected["classes"]
    if name == "yolo11n-detection":
        assert len(bundle.manifest.classes) == 80


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_manifest_md5_matches_bytes(models_dir: Path, name: str):
    """A stale md5 in model_info.json is a documentation bug; catch it."""
    import json

    folder = models_dir / name
    recorded = json.loads((folder / "model_info.json").read_text()).get("md5")
    assert recorded == md5_file(folder / "model.cvimodel")

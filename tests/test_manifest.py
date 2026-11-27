"""Model folders are validated strictly and messages are actionable."""

import json
from pathlib import Path

import pytest

from recamera.errors import ManifestError
from recamera.manifest import ModelManifest, load_bundle, load_manifest, manifest_from_dict, slugify


def test_load_valid_bundle(model_folder: Path):
    bundle = load_bundle(model_folder)
    assert bundle.manifest.classes == ["screw", "nut"]
    assert bundle.manifest.flow_name == "demo"
    assert bundle.size > 0
    assert len(bundle.md5) == 32


def test_load_bundle_accepts_bare_file(model_folder: Path):
    bundle = load_bundle(model_folder / "model.cvimodel")
    assert bundle.manifest.flow_name == "demo"


def test_missing_manifest_is_rejected(tmp_path: Path):
    folder = tmp_path / "x"
    folder.mkdir()
    (folder / "model.cvimodel").write_bytes(b"CviModel" + b"x")
    with pytest.raises(ManifestError, match="manifest not found"):
        load_bundle(folder)


def test_bad_magic_is_rejected(model_folder: Path):
    (model_folder / "model.cvimodel").write_bytes(b"NOTMODEL")
    with pytest.raises(ManifestError, match="not a compiled cvimodel"):
        load_bundle(model_folder)


def test_empty_model_is_rejected(model_folder: Path):
    (model_folder / "model.cvimodel").write_bytes(b"CviModel")
    with pytest.raises(ManifestError, match="empty"):
        load_bundle(model_folder)


def test_missing_classes_are_rejected(model_folder: Path):
    (model_folder / "model_info.json").write_text(json.dumps({"model_id": "1", "model_name": "x"}))
    with pytest.raises(ManifestError, match="class label"):
        load_bundle(model_folder)


def test_blank_class_is_rejected(model_folder: Path):
    (model_folder / "model_info.json").write_text(
        json.dumps({"model_id": "1", "model_name": "x", "classes": ["ok", " "]})
    )
    with pytest.raises(ManifestError, match="must not be blank"):
        load_bundle(model_folder)


def test_comma_in_class_is_rejected(model_folder: Path):
    (model_folder / "model_info.json").write_text(
        json.dumps({"model_id": "1", "model_name": "x", "classes": ["a,b"]})
    )
    with pytest.raises(ManifestError, match="commas"):
        load_bundle(model_folder)


@pytest.mark.parametrize("threshold", [1.5, -0.1])
def test_out_of_range_thresholds_are_rejected(model_folder: Path, threshold: float):
    (model_folder / "model_info.json").write_text(
        json.dumps(
            {
                "model_id": "1",
                "model_name": "x",
                "classes": ["a"],
                "thresholds": {"score": threshold, "iou": 0.4},
            }
        )
    )
    with pytest.raises(ManifestError, match="score must be between"):
        load_bundle(model_folder)


def test_invalid_json_is_reported_clearly(model_folder: Path):
    (model_folder / "model_info.json").write_text("{not json")
    with pytest.raises(ManifestError, match="not valid JSON"):
        load_bundle(model_folder)


def test_manifest_accepts_flat_and_nested_thresholds():
    flat = manifest_from_dict(
        {"model_id": "1", "model_name": "m", "classes": ["a"], "score": 0.7, "iou": 0.3}
    )
    assert flat.score == pytest.approx(0.7)
    nested = manifest_from_dict(
        {"model_id": "1", "model_name": "m", "classes": ["a"], "thresholds": {"score": 0.8, "iou": 0.2}}
    )
    assert nested.iou == pytest.approx(0.2)


def test_non_numeric_threshold_is_a_clear_error():
    with pytest.raises(ManifestError, match="threshold must be a number"):
        manifest_from_dict(
            {"model_id": "1", "model_name": "m", "classes": ["a"], "thresholds": {"score": "high"}}
        )


def test_classes_may_arrive_as_a_comma_string():
    manifest = manifest_from_dict({"model_id": "1", "model_name": "m", "classes": "screw, nut"})
    assert manifest.classes == ["screw", "nut"]


def test_default_flow_name_is_a_slug():
    manifest = ModelManifest(model_id="1", model_name="My Model.onnx", classes=["a"])
    assert manifest.flow_name == "My-Model"


def test_slugify_keeps_it_filesystem_safe():
    assert slugify("a/b c") == "a-b-c"
    assert slugify("   ") == "model"


def test_round_trip_json(model_folder: Path):
    manifest = load_manifest(model_folder / "model_info.json")
    reparsed = manifest_from_dict(json.loads(manifest.to_json()))
    assert reparsed.classes == manifest.classes
    assert reparsed.flow_name == manifest.flow_name
    assert reparsed.thresholds() == manifest.thresholds()


def test_payload_is_what_the_supervisor_stores():
    manifest = ModelManifest(model_id="7", model_name="m.onnx", classes=["a", "b"], score=0.25, iou=0.45)
    assert manifest.to_payload() == {
        "model_id": "7",
        "model_name": "m.onnx",
        "classes": ["a", "b"],
        "flow_name": "m",
        "thresholds": {"score": 0.25, "iou": 0.45},
    }

"""Flow patching points every model node at the deployed model."""

from recamera.manifest import ModelManifest
from recamera.nodered import flow_matches, patch_model_nodes

MANIFEST = ModelManifest(model_id="1", model_name="demo.onnx", classes=["screw", "nut"], score=0.5, iou=0.4)


def sample_flows():
    return [
        {"type": "tab", "id": "t"},
        {
            "type": "model",
            "id": "m1",
            "model": "old",
            "classes": "",
            "uri": "/some/file",
            "tscore": 0.9,
            "tiou": 0.9,
        },
        {"type": "function", "id": "f1", "func": "return msg;"},
    ]


def test_patch_sets_labels_name_thresholds_and_clears_uri():
    flows = sample_flows()
    assert patch_model_nodes(flows, MANIFEST) == 1
    node = flows[1]
    assert node["classes"] == "screw,nut"
    assert node["model"] == "demo"
    assert node["uri"] == ""
    assert node["tscore"] == 0.5
    assert node["tiou"] == 0.4


def test_patch_leaves_other_nodes_untouched():
    flows = sample_flows()
    before = [dict(n) for n in flows if n.get("type") != "model"]
    patch_model_nodes(flows, MANIFEST)
    after = [n for n in flows if n.get("type") != "model"]
    assert before == after


def test_patch_returns_zero_without_model_nodes():
    assert patch_model_nodes([{"type": "tab"}], MANIFEST) == 0


def test_flow_matches_detects_a_stale_flow():
    flows = sample_flows()
    assert not flow_matches(flows, MANIFEST)
    patch_model_nodes(flows, MANIFEST)
    assert flow_matches(flows, MANIFEST)


def test_flow_matches_requires_a_model_node():
    assert not flow_matches([{"type": "tab"}], MANIFEST)


def test_patch_is_idempotent():
    flows = sample_flows()
    patch_model_nodes(flows, MANIFEST)
    first = [dict(n) for n in flows]
    patch_model_nodes(flows, MANIFEST)
    assert flows == first

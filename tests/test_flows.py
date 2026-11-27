"""The /ws/boxes feed is installed into any flow that lacks it."""

import json
from pathlib import Path

import pytest

from recamera.flows import (
    FORMAT_BOXES_JS,
    WS_PATH,
    ensure_ws_feed,
    flow_summary,
    has_ws_feed,
    load_reference_flow,
)

REPO = Path(__file__).resolve().parent.parent
FACTORY = Path(__file__).resolve().parent / "fixtures_factory_flows.json"
REFERENCE = REPO / "tools" / "flows" / "recamera-ws-boxes.json"


def factory_flow():
    return json.loads(FACTORY.read_text())


def test_factory_flow_has_no_ws_feed():
    """This is the bug the patch exists for."""
    flows = factory_flow()
    assert not has_ws_feed(flows)
    summary = flow_summary(flows)
    assert summary["model_nodes"] == 1
    assert summary["ws_listener"] is False
    assert summary["ws_feed"] is False


def test_patch_adds_the_feed():
    flows = factory_flow()
    assert ensure_ws_feed(flows) is True
    assert has_ws_feed(flows)
    summary = flow_summary(flows)
    assert summary["ws_listener"] is True
    assert summary["stream_node"] is True


def test_patch_is_idempotent():
    flows = factory_flow()
    ensure_ws_feed(flows)
    snapshot = json.dumps(flows, sort_keys=True)
    assert ensure_ws_feed(flows) is False
    assert json.dumps(flows, sort_keys=True) == snapshot


def test_patch_preserves_every_existing_node():
    flows = factory_flow()
    before = {n["id"]: n for n in flows}
    ensure_ws_feed(flows)
    after = {n["id"]: n for n in flows}
    for node_id, node in before.items():
        assert node_id in after, f"node {node_id} disappeared"
        # existing nodes may only gain wires
        assert after[node_id].get("type") == node.get("type")


def test_patch_only_adds_four_nodes():
    flows = factory_flow()
    before = len(flows)
    ensure_ws_feed(flows)
    added = {n["type"] for n in flows[before:]}
    assert len(flows) - before == 4
    assert added == {"websocket-listener", "websocket out", "function", "stream"}


def test_wires_are_all_resolvable():
    flows = factory_flow()
    ensure_ws_feed(flows)
    ids = {n["id"] for n in flows}
    for node in flows:
        for group in node.get("wires") or []:
            for target in group:
                assert target in ids, f"{node.get('type')} wires to missing {target}"


def test_feed_survives_json_round_trip():
    flows = factory_flow()
    ensure_ws_feed(flows)
    reparsed = json.loads(json.dumps(flows))
    assert has_ws_feed(reparsed)
    assert ensure_ws_feed(reparsed) is False


def test_already_wired_flow_is_untouched():
    flows = load_reference_flow(REFERENCE)
    assert has_ws_feed(flows)
    snapshot = json.dumps(flows, sort_keys=True)
    assert ensure_ws_feed(flows) is False
    assert json.dumps(flows, sort_keys=True) == snapshot


def test_flow_without_model_is_left_alone():
    flows = [{"id": "t", "type": "tab", "label": "x"}]
    assert ensure_ws_feed(flows) is False
    assert len(flows) == 1


def test_listener_path_is_the_documented_one():
    assert WS_PATH == "/ws/boxes"


def test_reference_flow_matches_the_bundled_formatter():
    """The fixture and the generated node must stay in sync."""
    flows = load_reference_flow(REFERENCE)
    reference_fn = next(n for n in flows if n.get("type") == "function" and n.get("name") == "Format Boxes")
    assert reference_fn["func"].strip() == FORMAT_BOXES_JS.strip()


def test_reference_flow_has_the_required_nodes():
    flows = load_reference_flow(REFERENCE)
    summary = flow_summary(flows)
    assert summary["ws_listener"] and summary["ws_feed"] and summary["stream_node"]
    assert summary["model_nodes"] >= 1


@pytest.mark.parametrize("remove", ["websocket out", "mock-function"])
def test_detects_partial_setups(remove):
    """A listener without an outlet, or a formatter not wired through, is incomplete."""
    flows = load_reference_flow(REFERENCE)
    if remove == "websocket out":
        flows = [n for n in flows if n.get("type") != "websocket out"]
    else:
        # break the formatter -> outlet wire
        for node in flows:
            if node.get("type") == "function" and node.get("name") == "Format Boxes":
                node["wires"] = [[]]
    assert not has_ws_feed(flows)
    assert ensure_ws_feed(flows) is True
    assert has_ws_feed(flows)

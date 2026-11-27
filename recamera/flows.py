"""Ensure the Node-RED flow publishes detections on ``/ws/boxes``.

A factory-fresh reCamera runs a flow that has no websocket listener, so the
model's output never reaches ``ws://<ip>:1880/ws/boxes`` and the live viewer has
nothing to draw. Rather than replacing the whole flow (which would wipe any
custom app), this injects the four nodes the feed needs and only the wires
required to connect them:

    camera ──> model ──> Format Boxes ──> websocket out
        └──> stream (RTSP, for video)

Everything is idempotent: applying it to a flow that already works changes
nothing.

The reference copy of a complete working flow is kept at
``tools/flows/recamera-ws-boxes.json``.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

WS_PATH = "/ws/boxes"

# Turns the model node's raw payload into the JSON shape /ws/boxes publishes.
# Mirrors tools/flows/recamera-ws-boxes.json exactly.
FORMAT_BOXES_JS = """let p = msg.payload;
if (p && p.data && typeof p.data === 'object') p = p.data;
if (p && (Array.isArray(p.boxes) || Array.isArray(p.keypoints) || Array.isArray(p.segments))) {
    msg.payload = JSON.stringify({
        timestamp: Date.now(),
        boxes: (p.boxes || []).map(function(b) {
            return {x:b[0], y:b[1], w:b[2], h:b[3], score:b[4], class_id:b[5]};
        }),
        keypoints: p.keypoints || [],
        segments: p.segments || []
    });
    return msg;
}
return null;
"""


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _existing_ids(flows: list[dict]) -> set[str]:
    return {node.get("id") for node in flows if node.get("id")}


def _ws_listener(flows: list[dict]) -> dict | None:
    for node in flows:
        if node.get("type") == "websocket-listener" and node.get("path") == WS_PATH:
            return node
    return None


def _first_tab(flows: list[dict]) -> str | None:
    for node in flows:
        if node.get("type") == "tab":
            return node.get("id")
    return None


def _sscma_client(flows: list[dict]) -> str | None:
    """The client id the camera/model nodes use to reach SSCMA."""
    for node in flows:
        if node.get("type") == "sscma":
            return node.get("id")
    for node in flows:
        if node.get("type") in ("camera", "model") and node.get("client"):
            return node.get("client")
    return None


def _nodes_of_type(flows: list[dict], node_type: str) -> list[dict]:
    return [node for node in flows if node.get("type") == node_type]


def _wires(node: dict) -> list[list[str]]:
    return node.get("wires") or []


def _add_wire(node: dict, target: str) -> bool:
    """Append ``target`` to the node's first output; True if it was added."""
    wires = node.setdefault("wires", [[]])
    if not wires:
        wires.append([])
    if target in wires[0]:
        return False
    wires[0].append(target)
    return True


def has_ws_feed(flows: list[dict]) -> bool:
    """True when a model node reaches a websocket out on ``/ws/boxes``."""
    listener = _ws_listener(flows)
    if listener is None:
        return False

    by_id = {node.get("id"): node for node in flows}
    outlets = {
        node.get("id")
        for node in flows
        if node.get("type") == "websocket out" and node.get("server") == listener.get("id")
    }
    if not outlets:
        return False

    # Walk downstream from every model node looking for one of those outlets.
    for model in _nodes_of_type(flows, "model"):
        seen: set[str] = set()
        stack = [target for group in _wires(model) for target in group]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in outlets:
                return True
            node = by_id.get(current)
            if node:
                stack.extend(target for group in _wires(node) for target in group)
    return False


def ensure_ws_feed(flows: list[dict]) -> bool:
    """Add whatever is missing for ``/ws/boxes``; mutate ``flows`` in place.

    Returns True when nodes or wires were added. Safe to call repeatedly.
    """
    if has_ws_feed(flows):
        return False

    if not _nodes_of_type(flows, "model"):
        return False

    changed = False
    tab = _first_tab(flows)
    client = _sscma_client(flows)

    listener = _ws_listener(flows)
    if listener is None:
        listener = {
            "id": _new_id(),
            "type": "websocket-listener",
            "path": WS_PATH,
            "wholemsg": "false",
        }
        flows.append(listener)
        changed = True

    # An existing websocket out on this listener saves creating one.
    outlet = next(
        (
            node
            for node in flows
            if node.get("type") == "websocket out" and node.get("server") == listener["id"]
        ),
        None,
    )
    if outlet is None:
        outlet = {
            "id": _new_id(),
            "type": "websocket out",
            "z": tab,
            "name": "",
            "server": listener["id"],
            "client": "",
            "x": 1020,
            "y": 420,
            "wires": [],
        }
        flows.append(outlet)
        changed = True

    # Feed the outlet from the model through a formatter.
    formatter = next(
        (
            node
            for node in flows
            if node.get("type") == "function" and node.get("name") == "Format Boxes"
        ),
        None,
    )
    if formatter is None:
        formatter = {
            "id": _new_id(),
            "type": "function",
            "z": tab,
            "name": "Format Boxes",
            "func": FORMAT_BOXES_JS,
            "outputs": 1,
            "timeout": 0,
            "noerr": 0,
            "initialize": "",
            "finalize": "",
            "libs": [],
            "x": 800,
            "y": 420,
            "wires": [[outlet["id"]]],
        }
        flows.append(formatter)
        changed = True
    elif _add_wire(formatter, outlet["id"]):
        changed = True

    for model in _nodes_of_type(flows, "model"):
        if _add_wire(model, formatter["id"]):
            changed = True

    # Video: the viewer needs the RTSP stream node, not just boxes.
    if not _nodes_of_type(flows, "stream"):
        stream = {
            "id": _new_id(),
            "type": "stream",
            "z": tab,
            "name": "stream",
            "protocol": 0,
            "port": 554,
            "session": "live",
            "username": "admin",
            "password": "admin",
            "x": 590,
            "y": 60,
            "wires": [],
        }
        if client:
            stream["client"] = client
        flows.append(stream)
        changed = True
        for camera in _nodes_of_type(flows, "camera"):
            if _add_wire(camera, stream["id"]):
                changed = True

    return changed


def ensure_ws_feed_copy(flows: list[dict]) -> tuple[list[dict], bool]:
    """Non-mutating variant, handy for callers holding the original."""
    updated = copy.deepcopy(flows)
    return updated, ensure_ws_feed(updated)


def load_reference_flow(path) -> list[dict]:
    """Load the bundled known-good flow (tools/flows/recamera-ws-boxes.json)."""
    data = json.loads(path.read_text())
    return data.get("flows", data) if isinstance(data, dict) else data


def flow_summary(flows: list[dict]) -> dict[str, Any]:
    """Small dict for status output and tests."""
    return {
        "nodes": len(flows),
        "model_nodes": len(_nodes_of_type(flows, "model")),
        "ws_listener": _ws_listener(flows) is not None,
        "ws_feed": has_ws_feed(flows),
        "stream_node": bool(_nodes_of_type(flows, "stream")),
    }

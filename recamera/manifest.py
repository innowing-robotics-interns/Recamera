"""Model manifests: the ``model_info.json`` that describes a deployable model.

A model folder looks like this::

    models/screw-nut/
        model.cvimodel       compiled cv181x INT8 model (starts with "CviModel")
        model_info.json      this manifest

The manifest is the single source of truth for everything deployment needs, so
the camera can be driven from a folder with no other input.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ManifestError

MODEL_FILE = "model.cvimodel"
MANIFEST_FILE = "model_info.json"
MODEL_MAGIC = b"CviModel"
_CHUNK = 1024 * 1024

# The camera's flow node shows scores 0-100; the manifest keeps 0-1.
_MIN_SCORE = 0.0
_MAX_SCORE = 1.0
_MAX_CLASSES = 1000


def md5_file(path: Path) -> str:
    """Hex MD5 of a file, read in chunks."""
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def slugify(value: str) -> str:
    """A conservative slug used for model names on the camera."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or "model"


@dataclass
class ModelManifest:
    """Everything needed to deploy one model."""

    model_id: str
    model_name: str
    classes: list[str]
    flow_name: str = ""
    score: float = 0.5
    iou: float = 0.4
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.classes = [str(c).strip() for c in self.classes]
        if not self.flow_name:
            self.flow_name = slugify(Path(self.model_name).stem)

    # -- derived values -----------------------------------------------------

    @property
    def class_labels(self) -> str:
        """The comma-separated string the Node-RED model node expects."""
        return ",".join(self.classes)

    def thresholds(self) -> dict[str, float]:
        return {"score": round(float(self.score), 4), "iou": round(float(self.iou), 4)}

    def to_payload(self) -> dict[str, Any]:
        """The JSON the supervisor stores as ``model.json`` on the camera."""
        payload = {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "classes": list(self.classes),
            "flow_name": self.flow_name,
            "thresholds": self.thresholds(),
        }
        if self.description:
            payload["description"] = self.description
        return payload

    def to_json(self) -> str:
        """The ``model_info.json`` contents for a model folder."""
        record = dict(self.to_payload())
        record.update(self.extra)
        record.update(
            {
                "model_name": self.model_name,
                "flow_name": self.flow_name,
                "classes": list(self.classes),
                "thresholds": self.thresholds(),
            }
        )
        return json.dumps(record, indent=2) + "\n"

    # -- validation ---------------------------------------------------------

    def validate(self) -> None:
        if not self.model_id.strip():
            raise ManifestError("model_id must not be empty")
        if not self.model_name.strip():
            raise ManifestError("model_name must not be empty")
        if not self.classes:
            raise ManifestError("at least one class label is required")
        if len(self.classes) > _MAX_CLASSES:
            raise ManifestError(f"too many classes ({len(self.classes)} > {_MAX_CLASSES})")
        if any(not c for c in self.classes):
            raise ManifestError("class labels must not be blank")
        if any("," in c for c in self.classes):
            raise ManifestError("class labels must not contain commas (they are comma-joined)")
        if not _MIN_SCORE <= self.score <= _MAX_SCORE:
            raise ManifestError(f"score must be between 0 and 1, got {self.score}")
        if not _MIN_SCORE <= self.iou <= _MAX_SCORE:
            raise ManifestError(f"iou must be between 0 and 1, got {self.iou}")

    def __str__(self) -> str:
        return f"{self.flow_name} ({len(self.classes)} classes)"


@dataclass
class Bundle:
    """A validated model folder: manifest plus compiled model bytes."""

    path: Path
    manifest: ModelManifest
    model_path: Path

    @property
    def size(self) -> int:
        return self.model_path.stat().st_size

    @property
    def md5(self) -> str:
        return md5_file(self.model_path)

    def read_model(self) -> bytes:
        return self.model_path.read_bytes()

    def display(self) -> str:
        kib = self.size / 1024
        return f"{self.manifest} · {kib:,.0f} KiB · md5 {self.md5}"


def manifest_from_dict(data: dict[str, Any]) -> ModelManifest:
    """Build a manifest from JSON, accepting the shapes found on the camera."""
    thresholds = data.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        thresholds = {}
    classes = data.get("classes")
    if classes is None:
        classes = data.get("labels") or []
    if isinstance(classes, str):
        classes = [c.strip() for c in classes.split(",") if c.strip()]
    if not isinstance(classes, list):
        raise ManifestError("classes must be a list or comma-separated string")

    known = {"model_id", "model_name", "flow_name", "classes", "labels", "thresholds"}
    extra = {k: v for k, v in data.items() if k not in known}

    return ModelManifest(
        model_id=str(data.get("model_id") or "0"),
        model_name=str(data.get("model_name") or data.get("name") or "model"),
        classes=classes,
        flow_name=str(data.get("flow_name") or ""),
        score=_threshold(thresholds.get("score", data.get("score", 0.5))),
        iou=_threshold(thresholds.get("iou", data.get("iou", 0.4))),
        description=str(data.get("description") or ""),
        extra=extra,
    )


def _threshold(value: Any) -> float:
    """Parse a threshold, turning a bad value into an actionable error.

    Manifests are authored in this repo and must use 0-1; a percentage here is
    an authoring mistake, so it is rejected by ``validate`` rather than guessed
    at. (Wire payloads *are* 0-100 and are handled in ``detections``.)
    """
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"threshold must be a number, got {value!r}") from exc


def load_manifest(path: Path) -> ModelManifest:
    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{path} must contain a JSON object")
    return manifest_from_dict(data)


def load_bundle(path: Path) -> Bundle:
    """Load and validate a model folder (or a bare ``.cvimodel`` file).

    A bare file needs a manifest next to it; failing that it is rejected rather
    than guessed at, because wrong class labels silently produce wrong results.
    """
    path = path.expanduser().resolve()
    if path.is_file():
        manifest_path = path.with_name(MANIFEST_FILE)
        model_path = path
    elif path.is_dir():
        model_path = path / MODEL_FILE
        manifest_path = path / MANIFEST_FILE
        if not model_path.exists():
            raise ManifestError(f"{path} does not contain {MODEL_FILE}")
    else:
        raise ManifestError(f"model path does not exist: {path}")

    manifest = load_manifest(manifest_path)
    manifest.validate()

    if not model_path.exists():
        raise ManifestError(f"model not found: {model_path}")
    with model_path.open("rb") as handle:
        header = handle.read(len(MODEL_MAGIC))
    if header != MODEL_MAGIC:
        raise ManifestError(f"{model_path.name} is not a compiled cvimodel (bad header)")
    if model_path.stat().st_size == len(MODEL_MAGIC):
        raise ManifestError(f"{model_path.name} is empty")

    return Bundle(path=path, manifest=manifest, model_path=model_path)

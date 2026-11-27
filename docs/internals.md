# Internals

Reference material for working on the tool itself. For everyday use, see the
[README](../README.md).

## Repo layout

```
recamera/            the Python package
models/              ready-to-deploy models, one folder each
tools/               one-time Node-RED `Intl` fix
docs/                this file, conversion notes, manual web upload
tests/               automated tests
backups/             created at runtime, gitignored
```

Inside `recamera/`:

| File | Purpose |
| --- | --- |
| `cli.py` | The `recamera` command |
| `deploy.py` | Deploy / backup / restore engine |
| `manifest.py` | Reads and checks `model_info.json` |
| `api.py` | Camera management API client (chunked upload) |
| `nodered.py` | Patches the camera's Node-RED flow |
| `detections.py` | Normalises the detection feed |
| `stream.py` | Video + websocket receiver |
| `viewer.py`, `drawing.py` | Live viewer and box rendering |

## How deployment works

1. The model is uploaded in 512 KiB chunks; the camera stores it as
   `/userdata/Models/model.cvimodel` plus `model.json`.
2. The camera restarts its vision services (1–2 minutes).
3. The Node-RED `model` node is updated with class labels, thresholds, and
   name (`uri=""` so it uses the uploaded model).
4. The tool verifies the upload hash, re-reads the model description, checks
   the flow node, and watches `/ws/boxes` to prove detections flow.

A backup (`getModelFile` + `:1880/flows`) is taken before every deploy. Those
endpoints are open on the local network, which is why no login is needed.

## Two details the viewer handles

- **Class labels** are read from the camera, so `--labels` is optional.
- **Coordinates and scores**: `/ws/boxes` publishes boxes in the 1280×720
  preview space with scores as 0–100 integers. Both are converted, so boxes
  align with the 1920×1080 RTSP video and `69` prints as `0.69`.

## Model folder format

```
models/<name>/
  model.cvimodel      compiled cv181x INT8 model; must start with "CviModel"
  model_info.json     name, class labels, thresholds
```

```json
{
  "model_id": "my-model",
  "model_name": "my-model.onnx",
  "flow_name": "my-model",
  "classes": ["screw", "nut"],
  "thresholds": { "score": 0.5, "iou": 0.4 }
}
```

`recamera validate` checks the header, the manifest, non-empty comma-free
labels, and that thresholds are within 0–1.

## Configuration

Copy `.env.example` to `.env` to change the camera IP or RTSP credentials.

## Tests

```bash
uv sync --extra test
uv run pytest                                  # unit tests, no camera
RECAMERA_INTEGRATION=1 uv run pytest tests/test_integration_camera.py
```

The integration tests change the camera's model and restore it afterwards.

## Notes

- The camera must have Node-RED and SSCMA enabled (stock firmware default).
- `models/yolo11n-detection` holds the firmware's own stock model
  (`yolo11n_detection_cv181x_int8.cvimodel`, md5 `7819bd8d…`), so
  `recamera default` restores exactly what shipped.
- `backups/`, `.env`, `.venv/`, `.tpu/` and `.pt`/`.onnx` weights are
  gitignored; the ready-to-deploy `.cvimodel` files are tracked on purpose.

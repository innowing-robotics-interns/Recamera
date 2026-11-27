# reCamera model deployment

Deploy a compiled YOLO model to a Seeed Studio reCamera (SG2002 / cv181x), then
watch it run live. The compiled screw/nut model and the stock YOLO11n Detection
model are both in this repo, so deploying needs no conversion step and no
camera password.

Verified on reCamera Basic 64G (GC2053), firmware **0.2.4**: deploy the
screw/nut model → deploy the stock model → restore from backup → redeploy, with
detections checked in the live viewer each time.

## Quick start (uv)

Requires [uv](https://docs.astral.sh/uv/) and a reCamera reachable at
`192.168.42.1` (USB) or its Wi-Fi IP.

```bash
uv sync                       # create .venv and install everything
uv run recamera status        # device, services, current model
uv run recamera deploy models/screw-nut
uv run recamera view          # live video with boxes (labels come from the camera)
```

`recamera` is installed as a command by `uv sync`, so `uv run recamera …` always
uses the project environment. To use the old entry points, `uv run python
deploy.py …` and `uv run python view_live.py …` still work.

Prefer pip? `python3 -m venv .venv && . .venv/bin/activate && pip install -e .`

## Commands

| Command | What it does |
| --- | --- |
| `recamera status` | Firmware, service state, current model, model-node settings |
| `recamera deploy models/screw-nut` | Validate, back up, upload, patch the flow, verify the live stream |
| `recamera default` | Deploy the camera's stock YOLO11n Detection (COCO) model |
| `recamera backup [--note …]` | Save the current model file, manifest and full flow to `backups/` |
| `recamera restore [folder]` | Restore the newest backup, or a specific folder |
| `recamera list` | List the models bundled in this repo |
| `recamera validate models/<name>` | Check a model folder without touching the camera |
| `recamera wait` | Wait until Node-RED and SSCMA are running again |
| `recamera view` | Live RTSP/preview video with detection overlays |

Useful flags on `deploy`: `--force` (re-upload even when the bytes match),
`--labels screw nut`, `--name`, `--score 0.5`, `--iou 0.4`, `--no-backup`,
`--no-live`. `--ip 192.168.x.x` works on every command that talks to a camera
(and `RECAMERA_IP` sets the default).

Every deploy saves a backup first. `restore` ignores the safety snapshots it
creates itself, so running it twice is stable.

## What is in the repo

```
recamera/
  cli.py            recamera <command> entry point
  deploy.py         deploy / backup / restore engine
  manifest.py       model folder format and validation
  api.py            supervisor REST client (chunked upload)
  nodered.py        Node-RED admin client, model-node patching
  detections.py     normalises /ws/boxes payloads (scores, coordinates)
  stream.py         RTSP + websocket receiver
  viewer.py         live viewer
  drawing.py        box rendering
models/screw-nut/           compiled screw+nut model + model_info.json
models/yolo11n-detection/   stock YOLO11n Detection bytes + model_info.json
tools/install_intl_polyfill.sh   one-time Node-RED stability fix
docs/model-conversion.md    how to turn a new .pt into a .cvimodel
docs/manual-web-upload.md   manual web-UI fallback
tests/                      unit tests, plus opt-in camera integration tests
backups/                    created at runtime (gitignored)
```

## Adding a model

A model folder is two files:

```
models/<name>/
  model.cvimodel      compiled cv181x INT8 model; must start with "CviModel"
  model_info.json     name, class labels in training order, thresholds
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

`recamera validate models/<name>` checks the header, the manifest, that labels
are non-empty and comma-free, and that thresholds are within 0–1. Then
`recamera deploy models/<name>`.

Class labels **must** be in training order — id 0 is the first label. A wrong
order produces confident boxes with wrong names.

## One-time camera fix (important)

This firmware ships a Node.js build **without `Intl`**, which makes Node-RED's
translation layer crash with `ReferenceError: Intl is not defined`. That kills
Node-RED (and the dashboard/stream) at random. Install the bundled polyfill
once per camera, or after a firmware update:

```bash
./tools/install_intl_polyfill.sh
```

It copies `tools/intl-polyfill.js` to the camera, adds one `require(...)` line
to the user-writable `~/.node-red/settings.js` (backup:
`settings.js.bak-intl`), restarts Node-RED and waits until it is up. It is
idempotent. You will be prompted for the camera SSH password (user
`recamera`).

## How deployment works

1. `POST /api/deviceMgr/uploadModel` in 512 KiB chunks writes
   `/userdata/Models/model.cvimodel` and `model.json`; `model_info` rides on
   the final chunk.
2. The supervisor reloads Node-RED and SSCMA; this takes ~1–2 minutes, and the
   tool waits for both to be healthy.
3. The `model` node in the Node-RED flow is patched — class labels (training
   order), display name, confidence/IoU, `uri=""` — and the flow is posted to
   `:1880/flows`.
4. The tool verifies the model hash and recorded manifest, the flow node, and
   reads `/ws/boxes` to prove the pipeline is live.

Backups use `GET /api/deviceMgr/getModelFile` and `GET :1880/flows`, both open
on the local network, which is why no login is needed. An internet connection
is only needed to *convert* a new model, not to deploy a compiled one.

## Live viewer

```bash
uv run recamera view --save snapshot.jpg
uv run recamera view --seconds 10 --no-window --save snapshot.jpg   # headless
```

It reads the H.264 RTSP stream (1920×1080) and draws the boxes published on
`ws://<ip>:1880/ws/boxes`. Two things the viewer gets right for you:

- **Class labels** are read from the camera's deployed model, so nothing has to
  be passed by hand (`--labels` still overrides).
- **Coordinates and scores**: boxes are in the camera's 1280×720 preview space
  and scores are integers 0–100 on the wire. Both are normalised, so boxes land
  on the right pixels and `69` prints as `0.69`.

`q`/`Esc` closes the window. Defaults live in `.env.example`; copy it to `.env`
if your camera IP or RTSP credentials differ.

## Retraining / converting a new model

Conversion is separate from deployment:

1. Train YOLO11n detect (axis-aligned boxes) and keep the class order.
2. Export ONNX: `uv run --extra convert python pt_to_onnx.py best.pt`
   (or `yolo export model=best.pt format=onnx imgsz=640 opset=17 simplify=True
   dynamic=False`).
3. Convert ONNX → INT8 `.cvimodel` for `cv181x` using either the camera's
   **Model Conversion / SenseCraft** web flow, or the TPU-MLIR Docker toolchain
   in [docs/model-conversion.md](docs/model-conversion.md).
4. Create `models/<name>/` with the `.cvimodel` and a `model_info.json`, then
   `uv run recamera deploy models/<name>`.

A model much larger than YOLO11n at 640×640 may exceed the camera's memory and
leave the preview black.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `cannot reach 192.168.42.1` | Replug USB, wait ~20 s, `ping 192.168.42.1`; use `--ip` for Wi-Fi |
| Dashboard/stream dead, `:1880` closed, Node-RED `failed` | Run `./tools/install_intl_polyfill.sh` once; then `recamera wait`. If it persists, power-cycle |
| `camera already holds this exact model file; skipping upload` | Expected — use `--force` to re-upload |
| No boxes / black preview | Confirm the file is a YOLO11n-sized 640-input `.cvimodel`; check `recamera status` |
| Wrong box names | Labels must be in training order: fix `model_info.json` and redeploy |
| Viewer shows `ID:0` instead of names | The camera has no class list for the model; deploy with a `model_info.json` |
| Deploy looks stuck | First Node-RED start after boot can take 1–2 min; run `recamera status` |

## Testing

```bash
uv sync --extra test
uv run pytest                                        # unit tests, no camera
RECAMERA_INTEGRATION=1 uv run pytest tests/test_integration_camera.py
```

The integration tests change the model on the camera, restore the original at
the end, and should point at a camera you can afford to modify.

## Notes

- Tested firmware: reCamera OS 0.2.4; the API endpoints are local to the camera.
- The camera must have Node-RED/SSCMA enabled (stock firmware default).
- The bundled `models/yolo11n-detection` bytes are the firmware's own
  `yolo11n_detection_cv181x_int8.cvimodel` (md5 `7819bd8d…`), so `recamera
  default` restores exactly what shipped.
- `backups/`, `.env`, `.venv/` and the original `.pt`/`.onnx` weights are
  gitignored. The two ready-to-deploy `.cvimodel` files are tracked on purpose.

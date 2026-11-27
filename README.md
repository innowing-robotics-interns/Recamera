# reCamera model deployment

Deploy a compiled YOLO model to a Seeed Studio reCamera and view detections live.
reCamera Basic 64G (GC2053), firmware **0.2.4**.

## Quick start

```bash
ip -br addr | grep 192.168.42      # camera on USB; expect 192.168.42.x
uv sync                            # once per computer (needs uv)
uv run recamera status             # camera + services + current model
uv run recamera deploy models/screw-nut   # ~1-2 min
uv run recamera view               # live video with boxes; q to quit
```

Revert to the camera's stock YOLO model at any time:

```bash
uv run recamera default
```

`services … failed` on the first `status`? Run `./tools/install_intl_polyfill.sh` once, then repeat.

## Commands

Run from the repo root. `uv run` needs no venv activation.

| Command | Action |
| --- | --- |
| `uv run recamera status` | Camera, services, current model |
| `uv run recamera deploy models/<name>` | Deploy a model (backs up first) |
| `uv run recamera default` | Revert to the stock YOLO11n model |
| `uv run recamera view` | Live video with detections |
| `uv run recamera restore` | Undo: restore newest backup |
| `uv run recamera backup` | Save current model + flow |
| `uv run recamera list` | List bundled models |
| `uv run recamera wait` | Wait for services to be ready |
| `uv run recamera validate models/<name>` | Check a model folder |

Flags: `--ip 192.168.x.x` (any command, Wi-Fi) · `deploy`: `--force`,
`--labels screw nut`, `--score 0.5`, `--iou 0.4`, `--no-backup`, `--no-live` ·
`view`: `--save out.jpg`, `--seconds 10 --no-window`.

## Deploy session

```bash
uv run recamera deploy models/screw-nut     # writes a backup first
uv run recamera view                        # verify boxes in the live feed
uv run recamera status                      # confirm model + flow
uv run recamera default                     # when done, restore stock model
```

Success ends with `[+] deploy complete` and `live websocket: N messages`.
Camera UI: <http://192.168.42.1:1880/dashboard>.

## Bundled models

| Folder | Detects |
| --- | --- |
| `models/yolo11n-detection` | 80 COCO objects — the stock model |
| `models/screw-nut` | screw, nut |
| `models/yolo11n-screw-nut` | screw, nut (retrained) |
| `models/yolo11n-screw-nut-best` | screw, nut (retrained) |

Screw/nut models give false positives on other metal parts; retrain + calibrate
for production accuracy.

## Use your own model

The camera runs only `.cvimodel`, not `.pt`.

```
best.pt → best.onnx → model.cvimodel → deploy
```

**1. Export** (labels are positional: index 0 is the first class):

```bash
uv sync --extra convert
uv run python -c "from ultralytics import YOLO; print(YOLO('model/yolov11n_screw-nut_best.pt').names)"
uv run python pt_to_onnx.py model/yolov11n_screw-nut_best.pt
```

**2. Compile.** Either camera web UI (**Workspace → Model Conversion → Upload**,
camera needs internet) or locally:

```bash
uv venv --python 3.10 .tpu
uv pip install --python .tpu/bin/python \
  https://github.com/sophgo/tpu-mlir/releases/download/v1.30.2/tpu_mlir-1.30.2-py3-none-any.whl \
  'setuptools<81' 'onnx==1.17.0' onnxsim onnxslim psutil pyyaml torch

OUTPUTS='/model.23/cv2.0/cv2.0.2/Conv_output_0,/model.23/cv3.0/cv3.0.2/Conv_output_0,/model.23/cv2.1/cv2.1.2/Conv_output_0,/model.23/cv3.1/cv3.1.2/Conv_output_0,/model.23/cv2.2/cv2.2.2/Conv_output_0,/model.23/cv3.2/cv3.2.2/Conv_output_0'

.tpu/bin/model_transform --model_name mymodel \
  --model_def model/yolov11n_screw-nut_best.onnx \
  --input_shapes '[[1,3,640,640]]' --mean '0.0,0.0,0.0' \
  --scale '0.0039216,0.0039216,0.0039216' \
  --keep_aspect_ratio --pixel_format rgb --output_names "$OUTPUTS" \
  --mlir mymodel.mlir

.tpu/bin/run_calibration mymodel.mlir --dataset calibration --input_num 100 -o calib_table

.tpu/bin/model_deploy --mlir mymodel.mlir --quantize INT8 --quant_input \
  --processor cv181x --calibration_table calib_table \
  --customization_format RGB_PACKED --fuse_preprocess --aligned_input \
  --model mymodel.cvimodel
```

Calibration needs ~100 real camera frames in `calibration/`; this is what
determines accuracy.

**3. Package and deploy:**

```bash
mkdir -p models/my-model
cp mymodel.cvimodel models/my-model/model.cvimodel
```

`models/my-model/model_info.json`:

```json
{
  "model_id": "my-model",
  "model_name": "mymodel.onnx",
  "flow_name": "my-model",
  "classes": ["screw", "nut"],
  "thresholds": { "score": 0.5, "iou": 0.4 }
}
```

```bash
uv run recamera validate models/my-model
uv run recamera deploy models/my-model
```

Gotchas: labels must match training order · export at 640×640 · models much
larger than YOLO11n at 640 can exhaust camera memory (black preview) · poor
accuracy is almost always poor calibration.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `cannot reach 192.168.42.1` | Replug USB, wait ~20 s; on Wi-Fi use `--ip` |
| `services … failed` | `./tools/install_intl_polyfill.sh`, then `recamera wait` |
| Dashboard/video dead | Same; power-cycle if it persists |
| `skipping upload` | Normal; add `--force` to re-upload |
| Deploy seems stuck | First Node-RED start takes 1–2 min; run `status` |
| Boxes show `ID:0` | Set `classes` in `model_info.json` |
| Wrong objects boxed | Better training data + calibration |

## More

[docs/internals.md](docs/internals.md) · [docs/model-conversion.md](docs/model-conversion.md) · [docs/manual-web-upload.md](docs/manual-web-upload.md)

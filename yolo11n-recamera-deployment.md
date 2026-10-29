# YOLOv11n Deployment Guide & Execution Log: Seeed reCamera (SG2002)

This document records the exact commands and configuration steps for exporting and deploying a custom `weights.pt` (YOLO11n architecture) to the Seeed Studio reCamera.

---

## 1. Export `.pt` to ONNX

The reCamera conversion toolchain (TPU-MLIR) requires static input dimensions and supports a maximum opset version of **17**.

### Command (CLI)
Run using the Ultralytics CLI:

```bash
yolo export \
  model=weights.pt \
  format=onnx \
  imgsz=640 \
  opset=17 \
  simplify=True \
  dynamic=False
```

### Alternative: Python Script
If you prefer running from a Python script:

```python
from ultralytics import YOLO

# Load the trained checkpoint
model = YOLO("weights.pt")

# Export to ONNX with required parameters
model.export(
    format="onnx",
    imgsz=640,
    opset=17,
    simplify=True,
    dynamic=False,
)
```

### Verification
Verify that the exported model satisfies the opset and graph checks:

```bash
python -c 'import onnx; m = onnx.load("weights.onnx"); onnx.checker.check_model(m); print("IR:", m.ir_version, "Opsets:", [(x.domain, x.version) for x in m.opset_import])'
```

Expected output: Opset version must be $\le 17$.

---

## 2. Connecting the Camera to Network (Internet Access)

Seeed's Online Model Conversion requires the camera itself to have internet access to reach the conversion backend.

### Option 1: Wi-Fi (reCamera 2002w versions)
1. Open `http://192.168.42.1/#/network` in your browser.
2. Toggle on **Enable Wi-Fi**.
3. Select your local Wi-Fi SSID from the list, enter the password, and click **Confirm**.
4. Note the assigned **Wi-Fi IP** in the network settings so you can access it directly on your LAN.

*(Alternatively, connect your laptop/phone to the camera's default AP `reCamera_XXXXXX` with password `12345678` and configure at `http://192.168.16.1`).*

### Option 2: Ethernet
- Connect an RJ45 Ethernet cable from your router/switch to the reCamera's baseboard Ethernet port (requires external Type-C power; non-PoE by default).

### Option 3: Share PC Internet over USB (Windows Internet Connection Sharing)
If your reCamera model has no Wi-Fi module (non-w version) and no Ethernet cable:
1. In Windows: `Win + R` -> type `ncpa.cpl` (Network Connections).
2. Right-click your active Wi-Fi or Ethernet adapter with internet -> **Properties** -> **Sharing** tab.
3. Check **"Allow other network users to connect through this computer's Internet connection"**.
4. Under "Home networking connection", select the reCamera's RNDIS/USB adapter (the virtual Ethernet adapter showing `192.168.42.x`).

### Option 4: Configure Wi-Fi via CLI / SSH
You can open `http://192.168.42.1/#/terminal` or SSH directly into the camera:
```bash
ssh root@192.168.42.1
# Default password: recamera
```

#### Check Network Interfaces on Camera:
```bash
ip link show
# or
ifconfig -a
```

#### Scan for available Wi-Fi networks (if wireless interface exists, e.g. wlan0):
```bash
nmcli dev wifi list
# or using wpa_cli / iw
iw dev wlan0 scan | grep SSID
```

#### Connect to your Wi-Fi:
Using `nmcli`:
```bash
nmcli dev wifi connect "YOUR_SSID" password "YOUR_PASSWORD"
```

Or using `wpa_supplicant` / `wpa_cli`:
```bash
wpa_passphrase "YOUR_SSID" "YOUR_PASSWORD" >> /etc/wpa_supplicant.conf
wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant.conf
udhcpc -i wlan0
```

#### Route PC Internet via USB to reCamera (Windows NAT / ICS):
Your PC has Internet on **Wi-Fi** (`10.68.233.236`) and communicates with the camera via **Ethernet 2** (`192.168.42.154`).

**Step 1: Enable NAT/Sharing on Windows (Run in Administrator PowerShell on PC):**
```powershell
# In Windows PowerShell (Run as Administrator):
# Check adapter names
Get-NetAdapter

# Option A: GUI setup (Easiest)
# Run ncpa.cpl -> Right click "Wi-Fi" -> Properties -> Sharing -> Check "Allow other network users..." -> Select "Ethernet 2"
```

**Step 2: On the reCamera terminal, set default gateway and DNS:**
```bash
# Add default route via your PC (192.168.42.154)
ip route add default via 192.168.42.154 dev usb0

# Configure DNS
echo "nameserver 8.8.8.8" > /etc/resolv.conf
echo "nameserver 1.1.1.1" >> /etc/resolv.conf

# Verify connectivity
ping -c 3 8.8.8.8
ping -c 3 seeedstudio.com
```

#### If using physical Ethernet (eth0):
Plug the RJ45 cable from your router/network into the camera and run:
```bash
udhcpc -i eth0
ping -c 3 seeedstudio.com
```

#### Verify internet connection on the camera:
```bash
ping -c 3 seeedstudio.com
```

---

## 3. Deployment: Method A — Online Web Conversion (Recommended)

Requires the camera to have internet connectivity.

1. Open the camera web interface in your browser:
   ```
   http://192.168.42.1
   ```
   *(Default first-time login password is `recamera`)*
2. In the left navigation bar under device management, click **Model Conversion**.
3. Click **Upload Model** and select `weights.onnx`.
4. Wait for the cloud conversion to complete (progress indicator reaches 100% with a green checkmark).
5. Click **Use** on the converted model card.
6. Click the **Deploy** button in the top-right corner to apply changes to the Node-RED / SSCMA engine.
7. Open **Dashboard** (`http://192.168.42.1/#/dashboard`) to verify detections.

---

## 4. Deployment: Method B — Offline Compilation via Docker (TPU-MLIR)

Use this path if the camera has no internet access or custom heads are needed.

### 1. Start TPU-MLIR Container
```bash
docker pull sophgo/tpuc_dev:v3.1
docker run --privileged -v "$PWD:/workspace" -it sophgo/tpuc_dev:v3.1
```

Inside the container:
```bash
cd /workspace
pip install 'tpu_mlir[all]==1.7'
```

### 2. Extract Raw 6 Head Outputs
Open `weights.onnx` in [Netron](https://netron.app) to confirm the 6 convolution output tensor names before the detect layer:
```bash
OUTPUTS='/model.23/cv2.0/cv2.0.2/Conv_output_0,/model.23/cv3.0/cv3.0.2/Conv_output_0,/model.23/cv2.1/cv2.1.2/Conv_output_0,/model.23/cv3.1/cv3.1.2/Conv_output_0,/model.23/cv2.2/cv2.2.2/Conv_output_0,/model.23/cv3.2/cv3.2.2/Conv_output_0'
```

### 3. Convert to MLIR
```bash
model_transform \
  --model_name yolo11n \
  --model_def weights.onnx \
  --input_shapes '[[1,3,640,640]]' \
  --mean '0.0,0.0,0.0' \
  --scale '0.0039216,0.0039216,0.0039216' \
  --keep_aspect_ratio \
  --pixel_format rgb \
  --output_names "$OUTPUTS" \
  --test_input test.jpg \
  --test_result yolo11n_top_outputs.npz \
  --mlir yolo11n.mlir
```

### 4. Calibrate & Quantize to INT8 `.cvimodel`
Prepare `calibration/` folder with ~100 sample images, then run:
```bash
run_calibration yolo11n.mlir \
  --dataset calibration \
  --input_num 100 \
  -o yolo11n_calib_table

model_deploy \
  --mlir yolo11n.mlir \
  --quantize INT8 \
  --quant_input \
  --processor cv181x \
  --calibration_table yolo11n_calib_table \
  --test_input test.jpg \
  --test_reference yolo11n_top_outputs.npz \
  --customization_format RGB_PACKED \
  --fuse_preprocess \
  --aligned_input \
  --model weights_cv181x_int8.cvimodel
```

### 5. Upload via Node-RED
1. Go to `http://192.168.42.1/#/workspace`.
2. Double-click the **Model** node.
3. Choose **Upload** and upload `weights_cv181x_int8.cvimodel`.
4. Enter class labels in exact ID order (comma-separated or line-separated list mapping 0, 1, 2... to human-readable names).
5. Click **Done** and click **Deploy**.

---

## 5. Configuring Labels (0, 1, 2...) in Node-RED

By default, YOLO outputs numeric class indices:
- `0`, `1`, `2`, ...

To map these indices to human-readable names (e.g. `0 -> cat`, `1 -> dog`):

### Method 1: Inside the `model` Node (Recommended)
1. In `http://192.168.42.1/#/workspace`, **double-click the blue `model` node**.
2. Look for the **Labels** field.
3. Enter your labels in exact order separated by commas or lines:
   ```text
   person, bicycle, car, motorcycle...
   ```
   Index 0 gets the 1st name, index 1 gets the 2nd name, etc.
4. Click **Done**, then click **Deploy** (top-right).

### Method 2: Inside the `Model Info Handle` Function Node
If the dashboard extracts labels via code:
1. Double-click the peach-colored **`Model Info Handle`** function node.
2. Inside its JavaScript editor, look for where `msg.payload` or detections are handled. You can map indices to names:
   ```javascript
   const classNames = ["person", "car", "dog"]; // 0 -> person, 1 -> car, 2 -> dog
   if (msg.payload && msg.payload.boxes) {
       msg.payload.boxes.forEach(box => {
           box.label = classNames[box.target] || box.target;
       });
   }
   return msg;
   ```
3. Click **Done**, then **Deploy**.

---

## 6. The `Stream` Node & RTSP Video Streaming

The **Stream** node in the reCamera Node-RED palette exposes the camera's live video feed as an **RTSP (Real-Time Streaming Protocol)** stream over the network.

### What it does:
- Encodes the camera sensor output into an H.264 video stream.
- Runs an RTSP server directly on the camera hardware.
- Allows external software (VLC, OpenCV, OBS, Home Assistant, FFmpeg) to ingest real-time video without browser overhead.

### How to use it in Node-RED:
1. Drag the **Stream** node onto the canvas from the left palette (under the SSCMA category).
2. Connect the output of the **Camera** node into the input of the **Stream** node:
   ```text
   Camera  ──>  Stream
     │
     └──>  Model  ──>  Preview / Dashboard
   ```
3. Double-click the **Stream** node to view or change its settings:
   - **Port:** Default is `554` (or `8554`).
   - **Path / Session Name:** Usually `/live` or `/live0`.
   - **Credentials:** Optional username/password if authentication is required.
4. Click **Done** and hit **Deploy**.

### How to consume / view the stream:

#### 1. In VLC Media Player
- Open VLC -> **Media** -> **Open Network Stream...** (`Ctrl + N`).
- URL:
  ```text
  rtsp://192.168.42.1:554/live
  ```
  *(Or use the camera's LAN IP if connected to your local network).*

#### 2. In Python with OpenCV
```python
import cv2

rtsp_url = "rtsp://192.168.42.1:554/live"
cap = cv2.VideoCapture(rtsp_url)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break
    cv2.imshow("reCamera RTSP Feed", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

---

## 7. Streaming the Model Output (Video + Overlays vs. Metadata)

Can you pipe the output of the `model` node directly into `stream` to get video with drawn bounding boxes?

### Key Architecture Limitation:
- The **`camera` node** outputs raw image/video frames.
- The **`model` node** outputs **structured metadata** (JSON containing `boxes`, `target` class ID, confidence `score`), **not** a composite video stream with drawn boxes.
- The **`stream` node** expects a raw video frame buffer to encode into H.264 RTSP. If you connect `model -> stream`, it will fail or stream raw camera frames without bounding boxes.

### Option A: View Rendered Output in Browser (Built-in Web Preview)
The stock reCamera web interface already draws bounding boxes on top of the video in real-time using HTML5 Canvas:
- Dashboard: `http://192.168.42.1/#/dashboard`
- Preview Node: Wire `model -> preview`.

### Option B: Stream Metadata via MQTT or WebSockets (Best Practice for Edge AI)
Instead of re-encoding annotated video on the small edge chip (which burns CPU):
1. Use RTSP (`camera -> stream`) to stream clean video.
2. Stream detection coordinates over **MQTT** or **WebSocket**:
   - In Node-RED: `model -> mqtt out` (e.g. topic `recamera/detections`).
3. On your PC / client: Read the RTSP stream with OpenCV and overlay the bounding boxes from MQTT.

---

## 8. Dual-Stream Architecture: Clean RTSP Video + Low-Latency Metadata

This pattern provides maximum FPS: the camera's hardware encoder streams clean video via RTSP, while Node-RED emits bounding box coordinates asynchronously over WebSocket or MQTT.

### Flow Architecture in Node-RED

```text
               ┌──> stream (RTSP on port 554)
               │
camera ────────┼──> model ──> [Format Function] ──> websocket out (port 1880, path /ws/boxes)
                                                └──> (optional) mqtt out (topic recamera/boxes)
```

### 1. Configure the `stream` Node
- Connect `camera ──> stream`.
- Port: `554`, Path: `/live`.
- URL: `rtsp://192.168.42.1:554/live`

### 2. Configure the WebSocket / Metadata Output in Node-RED
1. Add a **function** node connected to `model`:
   ```javascript
   // Normalize and timestamp detections
   if (msg.payload && Array.isArray(msg.payload.boxes)) {
       msg.payload = {
           timestamp: Date.now(),
           boxes: msg.payload.boxes.map(b => ({
               x: b[0],
               y: b[1],
               w: b[2],
               h: b[3],
               score: b[4],
               class_id: b[5]
           }))
       };
       return msg;
   }
   return null;
   ```
2. Add a **websocket out** node from the network palette:
   - Type: `Listen on`
   - Path: `/ws/boxes`
   - Send: `payload`
3. Wire: `model ──> function ──> websocket out`.
4. Click **Deploy**.

### 3. Client Consumer Script (Python + OpenCV)
Run this script on your PC to ingest the video stream and overlay the real-time bounding boxes:

```python
import cv2
import json
import threading
import websocket

latest_boxes = []
lock = threading.Lock()

def on_message(ws, message):
    global latest_boxes
    try:
        data = json.loads(message)
        with lock:
            latest_boxes = data.get("boxes", [])
    except Exception:
        pass

def start_ws():
    ws = websocket.WebSocketApp("ws://192.168.42.1:1880/ws/boxes", on_message=on_message)
    ws.run_forever()

# Start background thread to receive bounding boxes
threading.Thread(target=start_ws, daemon=True).start()

# Read RTSP video feed
cap = cv2.VideoCapture("rtsp://192.168.42.1:554/live")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    h, w, _ = frame.shape
    with lock:
        boxes = list(latest_boxes)

    # Draw bounding boxes (assuming normalized coordinates [0, 1] or pixel coords)
    for b in boxes:
        # If coordinates are center-x, center-y, width, height (normalized):
        cx, cy, bw, bh = b["x"] * w, b["y"] * h, b["w"] * w, b["h"] * h
        x1, y1 = int(cx - bw / 2), int(cy - bh / 2)
        x2, y2 = int(cx + bw / 2), int(cy + bh / 2)
        score = b.get("score", 0.0)
        cls_id = b.get("class_id", 0)

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"ID:{cls_id} {score:.2f}", (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.imshow("reCamera: RTSP + WebSocket Overlay", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

---

## 9. Live Viewer Script: `view_live.py`

A ready-to-run live visualization script has been created at:
`C:\Users\lautl\Documents\Innowing\seeed studio\view_live.py`

### Usage:
```bash
python view_live.py --labels person bicycle car
```
- Queries system health, firmware version, and model list via the Supervisor REST API.
- Ingests RTSP video and WebSocket metadata feeds.
- Displays the live video window with bounding boxes, confidence scores, real-time viewer FPS, and detection counts. Press `q` or `Esc` to quit.

---

## 10. Python SDK: `recamera`

The project now includes a modular Python library under `recamera/` along with `requirements.txt` and `README.md`.

### Modules:
- `recamera.client.ReCamera`: Top-level unified context manager client.
- `recamera.stream.StreamReceiver`: Concurrent RTSP video + WebSocket metadata engine.
- `recamera.drawing.draw_detections`: OpenCV rendering for bounding boxes and labels.
- `recamera.analytics.ZoneMonitor` & `PersistenceFilter`: ROI intrusion zones and temporal false-positive suppression.
- `recamera.api.ReCameraAPI`: Supervisor HTTP REST client for device info, metrics, and model uploads.

See `README.md` for complete API documentation and usage examples.


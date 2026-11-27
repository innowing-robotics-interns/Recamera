# Upload a YOLO model to the reCamera (manual web UI)

> Reference fallback. The normal path is `recamera deploy models/<name>` as described in the [README](../README.md). Use this page only if you want to do the same steps by hand in the camera's web UI.

Use this when the camera is plugged in by USB and you have a trained YOLO **detect** model (upright boxes). A nano model such as YOLO11n fits this camera. A much larger model can leave the preview black.

Class names must stay in the same order as training. Example: id 0 is `screw`, id 1 is `nut`.

## 1. Export the model to ONNX

The camera accepts an ONNX file, not the `.pt` file.

```bash
yolo export model=your-model.pt format=onnx imgsz=640 opset=17 simplify=True dynamic=False
```

This creates `your-model.onnx` next to the `.pt` file.

## 2. Open the camera page

1. On this computer, open `http://192.168.42.1`.
2. Log in. The username is `recamera`; the password is the one set on the camera (the first-time default is `recamera`).

## 3. Sign in to SenseCraft

Conversion runs online, so this computer needs internet.

1. Open **Workspace**.
2. Click **Login to SenseCraft** and sign in.

## 4. Upload the ONNX file

1. Stay in **Workspace**.
2. Open the **Model Conversion** tab.
3. Click **Upload Model** and choose `your-model.onnx`.

## 5. Put the model on the camera

1. Wait until that model shows **Done**.
2. Click **Use**.

The camera switches over to this model.

## 6. Set the class names

**Use** does not fill in your class names. Set them yourself, in training order.

1. Open `http://192.168.42.1:1880`.
2. Double-click the **model** node.
3. Under **Class Labels**, enter the names in order.

Example for a model whose id 0 is screw and id 1 is nut:

```text
screw
nut
```

4. Click **Done**, then **Deploy**.

## 7. Check the preview

Open `http://192.168.42.1/#/dashboard`.

You should see the live picture with boxes and your class names. In the example, the labels are `screw` and `nut`.

## 8. Watch the stream from this computer

The camera also publishes the detections at:

```text
ws://<ip>:1880/ws/boxes
```

For this camera that is `ws://192.168.42.1:1880/ws/boxes`.

From this folder:

```bash
recamera view
```

That opens the camera picture and draws the boxes from `/ws/boxes`. Press `q` to close.

`recamera view` reads the class list from the camera, so it matches step 6 automatically; `--labels screw nut` still overrides it.

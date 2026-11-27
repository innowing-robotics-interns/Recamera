"""Live viewer: RTSP/preview video with detection overlays."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2

from .client import ReCamera
from .config import Config


def run_viewer(
    config: Config,
    labels: list[str] | None = None,
    seconds: float = 0,
    save: str | Path | None = None,
    window: bool = True,
    rtsp: bool = True,
    log=print,
) -> dict[str, Any]:
    """Show (or headlessly sample) the live stream.

    Returns a summary: ``{"frames", "max_boxes", "ws_messages", "saved"}``.
    """
    cam = ReCamera(
        camera_ip=config.camera_ip,
        labels=labels or [],
        rtsp_port=config.rtsp_port,
        rtsp_path=config.rtsp_path,
        rtsp_username=config.rtsp_user,
        rtsp_password=config.rtsp_pass,
        ws_port=config.ws_port,
        ws_path=config.ws_path,
        api_port=config.api_port,
        preview_size=config.preview_size,
        rtsp=rtsp,
    )

    log(f"[*] connecting to {cam.camera_ip}")
    # The deployed model's class list is the authoritative label order, so use
    # it whenever the caller did not supply one.
    try:
        manifest = cam.api.model_info()
    except Exception:
        manifest = None
    if manifest and not labels:
        cam.set_labels(manifest.classes)
        log(f"    model: {manifest.flow_name} — labels from the device manifest")
    elif manifest:
        log(f"    model: {manifest.flow_name} ({manifest.class_labels})")

    cam.connect()
    log(f"[*] video: {cam.rtsp_url if rtsp else '(preview frames from websocket)'}")
    log(f"[*] boxes: {cam.ws_url}")

    window_name = f"reCamera ({cam.camera_ip})"
    show_window = window
    if show_window:
        try:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        except cv2.error:
            show_window = False
            log("    [!] no display available; running headless")

    frames = 0
    max_boxes = 0
    last_rendered = None
    best_frame = None
    fps_count = 0
    fps_started = time.time()
    current_fps = 0.0
    started = time.time()

    try:
        while True:
            if seconds and time.time() - started >= seconds:
                break
            ok, frame, boxes = cam.read_frame()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            frames += 1
            fps_count += 1
            elapsed = time.time() - fps_started
            if elapsed >= 1.0:
                current_fps = fps_count / elapsed
                fps_count = 0
                fps_started = time.time()
                log(f"    fps={current_fps:.1f} boxes={len(boxes)} ws_msgs={cam.ws_messages}")

            rendered = cam.draw(frame, boxes)
            cv2.putText(
                rendered,
                f"FPS: {current_fps:.1f} | Detections: {len(boxes)}",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 255),
                2,
            )
            last_rendered = rendered
            if len(boxes) >= max_boxes:
                max_boxes = len(boxes)
                best_frame = rendered

            if show_window:
                cv2.imshow(window_name, rendered)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
            else:
                time.sleep(0.001)
            if seconds and time.time() - started >= seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cam.disconnect()
        if show_window:
            cv2.destroyAllWindows()

    saved = None
    if save:
        frame_to_save = best_frame if best_frame is not None else last_rendered
        if frame_to_save is not None:
            Path(save).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(save), frame_to_save)
            saved = str(save)
            log(f"[*] saved {save}")

    log(f"[*] done: {frames} frames, up to {max_boxes} detections, {cam.ws_messages} ws messages")
    return {
        "frames": frames,
        "max_boxes": max_boxes,
        "ws_messages": cam.ws_messages,
        "saved": saved,
    }

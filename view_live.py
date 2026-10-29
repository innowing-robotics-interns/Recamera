"""
Live viewer script using the recamera SDK:
- Connects to the Supervisor REST API to query device & model info
- Streams RTSP video and WebSocket bounding box metadata concurrently
- Displays real-time video with overlaid bounding boxes and confidence scores
"""

import argparse
import sys
import time
import cv2

from recamera import ReCamera


def main():
    parser = argparse.ArgumentParser(description="reCamera Live Detection Stream Viewer")
    parser.add_argument("--ip", default=None, help="reCamera IP address (or set RECAMERA_IP in .env)")
    parser.add_argument("--username", default=None, help="Supervisor API username (or set RECAMERA_USERNAME in .env)")
    parser.add_argument("--password", default=None, help="Supervisor API password (or set RECAMERA_PASSWORD in .env)")
    parser.add_argument("--rtsp-user", default=None, help="RTSP username (or set RECAMERA_RTSP_USER in .env)")
    parser.add_argument("--rtsp-pass", default=None, help="RTSP password (or set RECAMERA_RTSP_PASS in .env)")
    parser.add_argument("--rtsp-port", type=int, default=None, help="RTSP video port (or set RECAMERA_RTSP_PORT in .env)")
    parser.add_argument("--ws-port", type=int, default=None, help="Node-RED WebSocket port (or set RECAMERA_WS_PORT in .env)")
    parser.add_argument(
        "--labels",
        nargs="*",
        default=[],
        help="Optional list of class labels in ID order (e.g. --labels person car dog)",
    )
    args = parser.parse_args()

    # Client will automatically fallback to .env for any parameters passed as None
    cam = ReCamera(
        camera_ip=args.ip,
        labels=args.labels,
        rtsp_port=args.rtsp_port,
        rtsp_username=args.rtsp_user,
        rtsp_password=args.rtsp_pass,
        ws_port=args.ws_port,
    )
    print(f"[*] Initializing connection to reCamera at {cam.camera_ip}...")

    # 1. Query device & system telemetry via Supervisor REST API
    api_user = args.username or os.getenv("RECAMERA_USERNAME", "recamera")
    api_pass = args.password or os.getenv("RECAMERA_PASSWORD", "recamera")
    print(f"[*] Contacting Supervisor API (Port 80) as '{api_user}'...")
    if cam.api.login(api_user, api_pass):
        version_info = cam.api.get_version()
        sys_status = cam.api.get_system_status()
        models = cam.api.list_models()

        if version_info:
            print(f"    [Device] Firmware / OS: {version_info.get('data', version_info)}")
        if sys_status:
            print(f"    [Status] System Metrics: {sys_status.get('data', sys_status)}")
        if models:
            model_names = [m.get("model_name", m) if isinstance(m, dict) else str(m) for m in models]
            print(f"    [Models] Installed: {model_names}")
    else:
        print("    [!] Could not log into Supervisor API. Streaming will continue directly.")

    # 2. Connect RTSP & WebSocket dual-stream
    print("[*] Connecting video and metadata streams...")
    if not cam.connect():
        print(f"[!] Error: Could not connect to RTSP stream at rtsp://{args.ip}:{args.rtsp_port}/live")
        print("    Make sure the camera is running and the Node-RED 'stream' node is deployed.")
        sys.exit(1)

    print("\n[✓] Stream connected! Showing live window. Press 'q' to exit.\n")
    window_name = f"reCamera Live Stream ({args.ip})"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    fps_count = 0
    fps_start_time = time.time()
    current_fps = 0.0

    try:
        while True:
            ret, frame, boxes = cam.read_frame()
            if not ret:
                time.sleep(0.01)
                continue

            # Calculate viewer FPS
            fps_count += 1
            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                current_fps = fps_count / elapsed
                fps_count = 0
                fps_start_time = time.time()

            # Render bounding boxes onto the frame
            rendered = cam.draw(frame, boxes)

            # Draw HUD info (FPS and detected object count)
            hud_text = f"FPS: {current_fps:.1f} | Detections: {len(boxes)}"
            cv2.putText(
                rendered,
                hud_text,
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 255),
                2,
            )

            cv2.imshow(window_name, rendered)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:  # 'q' or Esc
                break

    except KeyboardInterrupt:
        pass
    finally:
        print("[*] Closing streams and releasing resources...")
        cam.disconnect()
        cv2.destroyAllWindows()
        print("[✓] Done.")


if __name__ == "__main__":
    main()

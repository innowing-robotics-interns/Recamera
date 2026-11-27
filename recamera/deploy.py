"""Deploy a compiled model to the camera, and manage backups.

The sequence, verified against firmware 0.2.4:

1. Validate the bundled model folder (manifest + ``CviModel`` header).
2. Wait for Node-RED/SSCMA to be healthy.
3. Back up the current model file, manifest and full flow.
4. Upload the model in 512 KiB chunks (skipped when the hash already matches).
5. Wait for the supervisor to serve the new file, then deploy the flow with
   the model node pointing at it, and wait for services again.
6. Verify the file hash, the recorded manifest and the flow node, and confirm
   the detection websocket is publishing.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .api import Supervisor
from .config import Config
from .errors import DeviceError, ReCameraError
from .manifest import Bundle, load_bundle, md5_bytes
from .nodered import NodeRed, flow_matches, patch_model_nodes

Log = Callable[[str], None]


def _default_log(message: str) -> None:
    print(message, flush=True)


@dataclass
class DeployResult:
    ok: bool
    uploaded: bool
    warnings: list[str]
    backup: Path | None = None

    def __bool__(self) -> bool:
        return self.ok


class Deployer:
    """Deploys model folders to one camera."""

    def __init__(
        self,
        config: Config | None = None,
        backup_dir: Path | None = None,
        log: Log = _default_log,
    ):
        self.config = config or Config.from_env()
        from .config import default_backup_dir

        self.backup_dir = Path(backup_dir or default_backup_dir())
        self.api = Supervisor(camera_ip=self.config.camera_ip, port=self.config.api_port)
        self.nodered = NodeRed(camera_ip=self.config.camera_ip, port=self.config.nodered_port)
        self.log = log
        self._last_progress_step = -1

    # -- health -------------------------------------------------------------

    def wait_until_ready(self, timeout: float = 300, min_wait: float = 0, settle: int = 8) -> bool:
        """Poll until the supervisor reports all services running and the flow started."""
        started = time.time()
        good = 0
        while time.time() - started < timeout:
            time.sleep(1)
            if time.time() - started < min_wait:
                continue
            ok = self.api.services_running() and self.nodered.state() == "start"
            good = good + 1 if ok else 0
            if good >= settle:
                return True
        return False

    def login(self, username: str | None = None, password: str | None = None) -> bool:
        return self.api.login(username or self.config.username, password or self.config.password)

    # -- backups ------------------------------------------------------------

    def backup(self, note: str = "", kind: str = "", quiet: bool = False) -> Path:
        """Save the served model, its manifest and the full flow."""
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        manifest = self.api.model_info()
        folder = self.backup_dir / f"{stamp}_{kind}{manifest.flow_name}"
        folder.mkdir(parents=True, exist_ok=True)

        model = self.api.model_file()
        (folder / "model.cvimodel").write_bytes(model)
        (folder / "model_info.json").write_text(manifest.to_json())

        meta: dict = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "device_ip": self.config.camera_ip,
            "note": note,
            "model_md5": md5_bytes(model),
            "model_name": manifest.model_name,
            "classes": manifest.classes,
        }
        try:
            flows, revision = self.nodered.get_flows()
            (folder / "flows.json").write_text(json.dumps({"rev": revision, "flows": flows}, indent=2) + "\n")
            meta["flow_revision"] = revision
        except ReCameraError as exc:
            meta["flows_error"] = str(exc)
            if not quiet:
                self.log(f"  ! flow not backed up ({exc})")
        (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        if not quiet:
            self.log(f"  backup: {folder}")
        return folder

    def latest_backup(self) -> Path | None:
        if not self.backup_dir.exists():
            return None
        folders = sorted(
            p for p in self.backup_dir.iterdir() if p.is_dir() and "_pre-restore_" not in p.name
        )
        return folders[-1] if folders else None

    # -- deploy -------------------------------------------------------------

    def deploy(
        self,
        source: Path,
        *,
        force: bool = False,
        no_backup: bool = False,
        no_live: bool = False,
        timeout: float = 300,
    ) -> DeployResult:
        return self.deploy_bundle(
            load_bundle(source), force=force, no_backup=no_backup, no_live=no_live, timeout=timeout
        )

    def deploy_bundle(
        self,
        bundle: Bundle,
        *,
        force: bool,
        no_backup: bool,
        no_live: bool,
        timeout: float,
    ) -> DeployResult:
        manifest = bundle.manifest
        target_md5 = bundle.md5
        warnings: list[str] = []
        # Warnings that mean the deploy did not land correctly; benign notices
        # (slow restart, backup skipped) go in ``warnings`` alone.
        problems: list[str] = []
        self._last_progress_step = -1
        self.log(f"[*] target: {manifest.flow_name} classes={manifest.class_labels} md5={target_md5}")

        info = self.api.device_info()
        if info:
            self.log(
                f"[*] device: {info.get('deviceName') or 'reCamera'} "
                f"fw={info.get('osVersion') or '?'} ip={info.get('ip') or self.config.camera_ip}"
            )

        if not self.api.services_running() or self.nodered.state() != "start":
            self.log("[*] waiting for Node-RED and SSCMA to be healthy...")
            if not self.wait_until_ready(timeout):
                raise DeviceError(
                    "Node-RED/SSCMA are not running; run `recamera status`, or install "
                    "the Intl polyfill (tools/install_intl_polyfill.sh) once"
                )

        backup_path = None
        if not no_backup:
            self.log("[*] backing up current model and flow")
            try:
                backup_path = self.backup(note=f"before deploying {manifest.flow_name}")
            except ReCameraError as exc:
                raise DeviceError(
                    f"could not back up the current state ({exc}); "
                    "use --no-backup to deploy anyway"
                ) from exc

        try:
            current_md5 = md5_bytes(self.api.model_file())
        except ReCameraError as exc:
            raise DeviceError(f"cannot read the current model from the camera: {exc}") from exc

        uploaded = force or current_md5 != target_md5
        if uploaded:
            reason = "forced" if force else f"{current_md5[:8]} -> {target_md5[:8]}"
            self.log(f"[*] uploading model ({reason})")
            self.api.upload_model(
                bundle.read_model(),
                manifest,
                progress=self._progress,
            )
            # The supervisor restarts its services after an upload.
            if not self.wait_until_ready(timeout, min_wait=20):
                warnings.append("services slow to settle after upload")
                self.log("  ! services are slow to settle; continuing to deploy the flow")
            if not self.api.wait_for_model_file(target_md5, timeout=120):
                warnings.append("device model file hash did not update")
                self.log("  ! device model file hash did not update")
        else:
            self.log("[*] camera already holds this exact model file; skipping upload")
            self.log("    (use --force to re-upload, e.g. to refresh metadata)")

        self.log("[*] patching the Node-RED model node")
        flows, _ = self.nodered.get_flows()
        if not patch_model_nodes(flows, manifest):
            raise DeviceError("no 'model' node found in the camera flow")
        self.nodered.deploy(flows)
        if not self.wait_until_ready(timeout, min_wait=5):
            warnings.append("services did not settle after flow deploy")
        if self.nodered.state() == "stop":
            self.nodered.set_state("start")

        # -- verification ---------------------------------------------------
        if uploaded:
            try:
                served = self.api.model_info()
                if served.model_name != manifest.model_name:
                    problems.append(
                        f"device model name is {served.model_name!r}, expected {manifest.model_name!r}"
                    )
                if served.classes != manifest.classes:
                    problems.append(
                        f"device classes are {served.classes!r}, expected {manifest.classes!r}"
                    )
            except ReCameraError as exc:
                problems.append(f"could not read back the device manifest: {exc}")

        try:
            flows_now, _ = self.nodered.get_flows()
            if not flow_matches(flows_now, manifest):
                problems.append("flow node does not match the requested model")
        except ReCameraError as exc:
            problems.append(f"could not verify the flow: {exc}")

        if not no_live:
            self.log("[*] checking the live detection stream (8s)")
            messages = self.check_live(seconds=8)
            if messages < 0:
                warnings.append("websocket-client unavailable; skipped the live check")
            elif messages == 0:
                problems.append("no messages on /ws/boxes")
                self.log("  ! no websocket messages; the model node may not be wired to /ws/boxes")
            else:
                self.log(f"  live websocket: {messages} messages")

        all_warnings = problems + warnings
        for warning in all_warnings:
            self.log(f"  ! {warning}")
        result = DeployResult(ok=not problems, uploaded=uploaded, warnings=all_warnings, backup=backup_path)
        if result.ok:
            self.log("[+] deploy complete")
            self.log(f"    dashboard: http://{self.config.camera_ip}:1880/dashboard")
            self.log(f"    viewer:    recamera view --labels {' '.join(manifest.classes)}")
        else:
            self.log("[-] deploy finished with warnings; run `recamera status` for details")
        return result

    def _progress(self, percent: float) -> None:
        # Print at 25% steps so a 3 MB upload does not flood the terminal.
        step = int(percent // 25)
        if step >= 1 and step > self._last_progress_step:
            self._last_progress_step = step
            self.log(f"    upload {min(100, step * 25)}%")

    # -- live check ---------------------------------------------------------

    def _ws_url(self, ws_port: int | None = None) -> str:
        port = ws_port or self.config.ws_port
        return f"ws://{self.config.camera_ip}:{port}{self.config.ws_path}"

    def check_live(self, seconds: float = 8, ws_port: int | None = None) -> int:
        """Count messages on the detection websocket; -1 if the library is missing."""
        try:
            import threading

            import websocket
        except ImportError:
            return -1

        count = 0
        connected = threading.Event()
        lock = threading.Lock()

        def on_open(_ws):
            connected.set()

        def on_message(_ws, _message):
            nonlocal count
            with lock:
                count += 1

        app = websocket.WebSocketApp(
            self._ws_url(ws_port), on_open=on_open, on_message=on_message
        )
        thread = threading.Thread(target=app.run_forever, daemon=True)
        thread.start()
        # Count for ``seconds`` of *connected* time, not for a fixed wall clock
        # starting before the connection is even established.
        connected.wait(timeout=5)
        time.sleep(seconds)
        app.close()
        thread.join(timeout=2)
        return count

    # -- restore ------------------------------------------------------------

    def restore(
        self,
        backup: Path | None = None,
        *,
        force: bool = False,
        no_backup: bool = False,
        timeout: float = 300,
    ) -> DeployResult:
        folder = backup or self.latest_backup()
        if folder is None:
            raise ReCameraError("no backups found; run `recamera backup` first")
        folder = Path(folder)
        model_path = folder / "model.cvimodel"
        manifest_path = folder / "model_info.json"
        if not model_path.exists() or not manifest_path.exists():
            raise ReCameraError(f"{folder} is not a complete backup")

        manifest = load_bundle(folder).manifest
        if not no_backup:
            self.log("[*] backing up the current state before restore")
            self.backup(note=f"before restoring {folder.name}", kind="pre-restore_")

        try:
            current_md5 = md5_bytes(self.api.model_file())
        except ReCameraError:
            current_md5 = ""
        if not self.api.services_running() or self.nodered.state() != "start":
            self.log("[*] waiting for Node-RED and SSCMA to be healthy...")
            if not self.wait_until_ready(timeout):
                raise DeviceError("Node-RED/SSCMA are not running; run `recamera wait` first")

        target_md5 = md5_bytes(model_path.read_bytes())
        uploaded = force or current_md5 != target_md5
        problems: list[str] = []
        if uploaded:
            self.log(f"[*] restoring model file from {folder.name}")
            self.api.upload_model(model_path.read_bytes(), manifest, progress=self._progress)
            if not self.wait_until_ready(timeout, min_wait=20):
                problems.append("services did not settle after upload")
            if not self.api.wait_for_model_file(target_md5, timeout=120):
                problems.append("device model file hash did not update")
        else:
            self.log("[*] camera already holds this model file; skipping upload")

        flow_file = folder / "flows.json"
        if flow_file.exists():
            saved = json.loads(flow_file.read_text())
            flows = saved.get("flows", saved) if isinstance(saved, dict) else saved
            self.nodered.deploy(flows)
            self.wait_until_ready(timeout, min_wait=5)
            if self.nodered.state() == "stop":
                self.nodered.set_state("start")
            self.log("[+] flow restored")
        else:
            self.log("  ! backup has no flows.json; restored the model only")
        self.log("[+] restore complete")
        return DeployResult(ok=True, uploaded=uploaded, warnings=[])

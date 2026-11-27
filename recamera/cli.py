"""Command line interface: ``recamera <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from .config import Config, default_backup_dir, default_models_dir
from .deploy import Deployer
from .errors import ManifestError, ReCameraError
from .manifest import load_bundle


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recamera",
        description="Deploy compiled YOLO models to a Seeed reCamera and view live detections.",
    )
    parser.add_argument("--ip", help="camera address (default: RECAMERA_IP or 192.168.42.1)")
    parser.add_argument("--timeout", type=int, default=300, help="seconds to wait for services (default 300)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON where supported")

    sub = parser.add_subparsers(dest="command", required=True)

    def connection(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--ip", dest="cmd_ip", help="camera address for this command")
        parser.add_argument("--timeout", dest="cmd_timeout", type=int, help="service timeout in seconds")

    status = sub.add_parser("status", help="show device, services, current model and flow")

    deploy = sub.add_parser("deploy", help="deploy a model folder (e.g. models/screw-nut)")
    deploy.add_argument("source", type=Path, nargs="?", help="model folder or .cvimodel file")
    deploy.add_argument("--name", help="override the model / flow node display name")
    deploy.add_argument("--labels", nargs="+", help="override the class labels (training order)")
    deploy.add_argument("--score", type=float, help="override the confidence threshold (0-1)")
    deploy.add_argument("--iou", type=float, help="override the IoU threshold (0-1)")
    deploy.add_argument("--force", action="store_true", help="upload even when the camera has this file")
    deploy.add_argument("--no-backup", action="store_true", help="skip the pre-deploy backup")
    deploy.add_argument("--no-live", action="store_true", help="skip the websocket live check")

    default = sub.add_parser("default", help="restore the camera's stock YOLO11n Detection model")
    default.add_argument("--force", action="store_true")
    default.add_argument("--no-backup", action="store_true")
    default.add_argument("--no-live", action="store_true")

    backup = sub.add_parser("backup", help="save the current model, manifest and flow")
    backup.add_argument("--note", default="", help="note stored in meta.json")

    restore = sub.add_parser("restore", help="restore a backup (default: newest)")
    restore.add_argument("backup", nargs="?", type=Path)
    restore.add_argument("--force", action="store_true")
    restore.add_argument("--no-backup", action="store_true")

    listing = sub.add_parser("list", help="list bundled models and models bundled with this repo")
    waiting = sub.add_parser("wait", help="wait until Node-RED and SSCMA are running")

    validate = sub.add_parser("validate", help="check a model folder before deploying it")
    validate.add_argument("source", type=Path)

    view = sub.add_parser("view", help="live video with detection overlays")
    view.add_argument("--labels", nargs="*", default=None, help="class labels in id order")
    view.add_argument("--seconds", type=float, default=0, help="stop after N seconds (0 = until q)")
    view.add_argument("--save", default=None, help="write the best annotated frame here")
    view.add_argument("--no-window", action="store_true", help="run headless")
    view.add_argument("--no-rtsp", action="store_true", help="use preview frames from the websocket only")

    for command in (deploy, default, restore, view, status, backup, listing, waiting):
        connection(command)
    return parser


def _config(args: argparse.Namespace) -> Config:
    config = Config.from_env()
    ip = getattr(args, "cmd_ip", None) or args.ip
    if ip:
        config.camera_ip = ip
    timeout = getattr(args, "cmd_timeout", None) or args.timeout
    args.timeout = timeout
    return config


def _deployer(args: argparse.Namespace) -> Deployer:
    return Deployer(config=_config(args), backup_dir=default_backup_dir())


def _apply_overrides(bundle, args) -> None:
    """Apply --name/--labels/--score/--iou to the loaded manifest in place."""
    manifest = bundle.manifest
    if args.name:
        manifest.model_name = args.name
        manifest.flow_name = ""
        manifest.__post_init__()
    if args.labels:
        manifest.classes = args.labels
    if args.score is not None:
        manifest.score = args.score
    if args.iou is not None:
        manifest.iou = args.iou
    manifest.validate()


def cmd_status(args: argparse.Namespace, as_json: bool) -> int:
    from .api import SERVICE_NAMES

    deployer = _deployer(args)
    api, nodered = deployer.api, deployer.nodered
    info = api.device_info()
    status = api.service_status()
    model = None
    model_error = None
    try:
        model = api.model_info()
    except ReCameraError as exc:
        model_error = str(exc)
    flows, revision, nodes = [], None, []
    try:
        flows, revision = nodered.get_flows()
        nodes = nodered.model_nodes(flows)
    except ReCameraError:
        pass

    reachable = bool(info) or bool(status)
    payload = {
        "device": {"name": info.get("deviceName"), "firmware": info.get("osVersion"), "ip": info.get("ip")},
        "services": {
            k: SERVICE_NAMES.get(v, "?")
            for k, v in status.items()
            if k in ("nodeRed", "sscmaNode", "system")
        },
        "model": None if model is None else model.to_payload(),
        "model_error": model_error,
        "flow": {"revision": revision, "model_nodes": nodes},
    }
    exit_code = 0 if reachable and not model_error else 1
    if as_json:
        import json

        print(json.dumps(payload, indent=2))
        return exit_code

    print(
        f"device   {info.get('deviceName', '?')}  fw {info.get('osVersion', '?')}  "
        f"ip {info.get('ip', api.camera_ip)}"
    )
    print(
        "services "
        f"node-red={SERVICE_NAMES.get(status.get('nodeRed'), '?')}  "
        f"sscma={SERVICE_NAMES.get(status.get('sscmaNode'), '?')}  "
        f"system={SERVICE_NAMES.get(status.get('system'), '?')}"
    )
    if model:
        print(f"model    {model.model_name}  classes={len(model.classes)}  flow={model.flow_name}")
        if model.classes:
            shown = ", ".join(model.classes[:12])
            print(f"         {shown}{' ...' if len(model.classes) > 12 else ''}")
    else:
        print(f"model    unavailable ({model_error})")
    if nodes:
        print(f"node-red flow rev {revision}  model nodes {len(nodes)}")
        for node in nodes:
            print(
                f"         name={node.get('model')} score={node.get('tscore')} iou={node.get('tiou')} "
                f"classes={str(node.get('classes', ''))[:60]}"
            )
    else:
        print("node-red flow unavailable")
    if not api.services_running():
        print("hint     if Node-RED stays failed, run tools/install_intl_polyfill.sh once")
    return exit_code


def cmd_deploy(args: argparse.Namespace) -> int:
    deployer = _deployer(args)
    source = args.source or default_models_dir() / "screw-nut"
    bundle = load_bundle(source)
    _apply_overrides(bundle, args)
    result = deployer.deploy_bundle(
        bundle,
        force=args.force,
        no_backup=args.no_backup,
        no_live=args.no_live,
        timeout=args.timeout,
    )
    return 0 if result.ok else 1


def cmd_default(args: argparse.Namespace) -> int:
    stock = default_models_dir() / "yolo11n-detection"
    deployer = _deployer(args)
    result = deployer.deploy(
        stock,
        force=args.force,
        no_backup=args.no_backup,
        no_live=args.no_live,
        timeout=args.timeout,
    )
    return 0 if result.ok else 1


def cmd_backup(args: argparse.Namespace) -> int:
    path = _deployer(args).backup(note=args.note)
    print(path)
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    result = _deployer(args).restore(
        args.backup, force=args.force, no_backup=args.no_backup, timeout=args.timeout
    )
    return 0 if result.ok else 1


def cmd_wait(args: argparse.Namespace) -> int:
    deployer = _deployer(args)
    print("[*] waiting for Node-RED and SSCMA...", flush=True)
    if deployer.wait_until_ready(args.timeout, settle=10):
        print("[+] services are running")
        return 0
    print("[-] services did not become healthy; see `recamera status`")
    return 1


def cmd_list(args: argparse.Namespace, as_json: bool) -> int:
    models_dir = default_models_dir()
    bundled = []
    if models_dir.exists():
        for folder in sorted(models_dir.iterdir()):
            candidate = folder / "model.cvimodel"
            if not folder.is_dir() or not candidate.exists():
                continue
            try:
                bundle = load_bundle(folder)
            except ManifestError as exc:
                bundled.append({"folder": folder.name, "error": str(exc)})
                continue
            bundled.append(
                {
                    "folder": folder.name,
                    "flow_name": bundle.manifest.flow_name,
                    "classes": bundle.manifest.classes,
                    "md5": bundle.md5,
                    "size": bundle.size,
                }
            )
    if as_json:
        import json

        print(json.dumps(bundled, indent=2))
        return 0
    print(f"bundled models ({models_dir}):")
    for item in bundled:
        if "error" in item:
            print(f"  {item['folder']:<22} INVALID: {item['error']}")
        else:
            print(
                f"  {item['folder']:<22} {item['flow_name']:<28} "
                f"classes={','.join(item['classes'])[:48]} md5={item['md5'][:8]}"
            )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.source)
    print(f"[+] {args.source} is valid")
    print(f"    {bundle.display()}")
    print(f"    model_name: {bundle.manifest.model_name}")
    print(f"    flow_name:  {bundle.manifest.flow_name}")
    print(f"    classes:    {', '.join(bundle.manifest.classes)}")
    thresholds = bundle.manifest.thresholds()
    print(f"    thresholds: score={thresholds['score']} iou={thresholds['iou']}")
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    from .viewer import run_viewer

    config = _config(args)
    summary = run_viewer(
        config,
        labels=args.labels,
        seconds=args.seconds,
        save=args.save,
        window=not args.no_window,
        rtsp=not args.no_rtsp,
    )
    return 0 if summary["frames"] > 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return cmd_status(args, args.json)
        if args.command == "deploy":
            return cmd_deploy(args)
        if args.command == "default":
            return cmd_default(args)
        if args.command == "backup":
            return cmd_backup(args)
        if args.command == "restore":
            return cmd_restore(args)
        if args.command == "wait":
            return cmd_wait(args)
        if args.command == "list":
            return cmd_list(args, args.json)
        if args.command == "validate":
            return cmd_validate(args)
        if args.command == "view":
            return cmd_view(args)
    except (ManifestError, UnicodeDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except requests.ConnectionError:
        print("error: cannot reach the camera; check USB/Wi-Fi and the IP", file=sys.stderr)
        return 1
    except ReCameraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())

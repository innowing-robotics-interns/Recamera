#!/usr/bin/env python3
"""Export a trained YOLO checkpoint to ONNX for reCamera conversion.

Usage:
    uv run --extra convert pt_to_onnx.py weights.pt [output.onnx]

The camera's TPU-MLIR toolchain needs a static input shape (640x640) and an
opset no newer than 17; this script sets both.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    weights = Path(argv[0])
    if not weights.exists():
        print(f"error: {weights} not found", file=sys.stderr)
        return 1
    try:
        from ultralytics import YOLO
    except ImportError:
        print(
            "error: ultralytics is not installed; run `uv sync --extra convert`",
            file=sys.stderr,
        )
        return 1

    model = YOLO(str(weights))
    exported = model.export(format="onnx", imgsz=640, opset=17, simplify=True, dynamic=False)
    print(f"[+] exported {exported}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

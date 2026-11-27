#!/usr/bin/env python3
"""Backwards-compatible entry point for ``recamera``.

The implementation lives in :mod:`recamera.cli`; this wrapper lets existing
commands such as ``python deploy.py deploy models/screw-nut`` keep working.
"""

import sys

from recamera.cli import main

if __name__ == "__main__":
    sys.exit(main())

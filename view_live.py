#!/usr/bin/env python3
"""Backwards-compatible entry point for the live viewer.

The implementation lives in :mod:`recamera.viewer`; ``recamera view`` is the
canonical command.
"""

import sys

from recamera.cli import main

if __name__ == "__main__":
    # Map the old standalone flags onto the ``view`` command.
    argv = ["view", *sys.argv[1:]]
    sys.exit(main(argv))

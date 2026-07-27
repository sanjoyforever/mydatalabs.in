"""Thin wrapper kept for the documented `python scripts/update_hormuz.py` path.

The updater itself lives in update_data.py at the project root so there is one
implementation rather than two that can drift apart.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_data import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

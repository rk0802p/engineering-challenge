"""Pytest configuration and sys.path setup for Task 4 tests."""

from pathlib import Path
import sys

# Ensure submission root directory is always on sys.path
submission_root = Path(__file__).resolve().parent.parent
if str(submission_root) not in sys.path:
    sys.path.insert(0, str(submission_root))

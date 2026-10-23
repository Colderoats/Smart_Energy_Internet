r"""Shared setup for the software-only test cases TC01-TC05 (see tests/README.md).
Run with the BACKEND venv:  backendenv\Scripts\python -m pytest tests -q
(TC02 needs the testbed venv, TC04 is a Hardhat script - see the README.)"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.environ.setdefault("RUN_BACKGROUND_TASKS", "false")
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
sys.path.insert(0, str(REPO / "backend"))

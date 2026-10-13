"""Artifact locations for the testbed models (no heavy imports, safe in every venv)."""
from pathlib import Path

ART = Path(__file__).resolve().parents[1] / "artifacts" / "testbed"

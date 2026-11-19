"""Shared test helpers."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fx(name: str) -> dict:
    """Load a payload captured from a real Naim Atom (see tests/fixtures)."""
    return json.loads((FIXTURES / f"{name}.json").read_text())

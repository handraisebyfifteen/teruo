"""JSON state persistence for the inventory agent."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


STATE_PATH = Path(
    os.environ.get("INVENTORY_STATE_PATH", Path(__file__).parent / "data" / "state.json")
)


def load_state() -> dict[str, Any]:
    with STATE_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_state(state: dict[str, Any]) -> None:
    """Persist state atomically so an interrupted write cannot corrupt the file."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=STATE_PATH.parent, prefix=".state-", suffix=".json"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_name, STATE_PATH)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
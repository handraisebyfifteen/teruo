"""JSON state persistence for the inventory agent."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


STATE_PATH = Path(
    os.environ.get("INVENTORY_STATE_PATH", Path(__file__).parent / "data" / "state.json")
)


class StateConflictError(RuntimeError):
    """Raised when state.json changed on disk after this process loaded it."""


# In-process serialization. The agent sometimes runs tools in parallel;
# without this, load→save cycles interleave and a later write clobbers an
# earlier one. The tools wrap each whole read-write cycle in this lock.
# Cross-process conflicts (two people running separately) are still caught
# by the hash comparison below.
STATE_LOCK = threading.RLock()

# Hash of the most recently loaded state.json; save_state compares against it.
_loaded_digest: str | None = None


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_state() -> dict[str, Any]:
    global _loaded_digest
    raw = STATE_PATH.read_bytes()
    _loaded_digest = _digest(raw)
    return json.loads(raw.decode("utf-8"))


def save_state(state: dict[str, Any]) -> None:
    """Persist state atomically, refusing to clobber another writer's update.

    Just before writing, read the file once more; if it differs from what
    this process loaded, raise StateConflictError and abort (instructions
    1-4). No full locking machinery — the only goal is that numbers never
    silently vanish.
    """
    global _loaded_digest
    if _loaded_digest is not None and STATE_PATH.exists():
        if _digest(STATE_PATH.read_bytes()) != _loaded_digest:
            raise StateConflictError("state.json was modified by another writer")

    raw = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=STATE_PATH.parent, prefix=".state-", suffix=".json"
    )
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(raw)
        os.replace(temporary_name, STATE_PATH)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    _loaded_digest = _digest(raw)


def archive_and_reset(stamp: str) -> Path:
    """Set the current state aside and start from an empty one.

    Nothing is deleted: the file is renamed next to itself with ``stamp`` in
    the name, so a reset the owner regrets is undone by moving it back. The
    language choice survives — it belongs to the screen, not the shop.
    """
    archive = STATE_PATH.with_name(f"{STATE_PATH.stem}.{stamp}{STATE_PATH.suffix}")
    language = None
    if STATE_PATH.exists():
        try:
            language = (load_state().get("config") or {}).get("language")
        except (ValueError, OSError):
            language = None
        os.replace(STATE_PATH, archive)
    fresh: dict[str, Any] = {"products": [], "items": [], "history": []}
    if language:
        fresh["config"] = {"language": language}
    save_state(fresh)
    return archive

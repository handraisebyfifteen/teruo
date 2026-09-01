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


# プロセス内の直列化。エージェントはツールを並列に実行することがあり、
# その場合 load→save の読み書きが交錯して後書きが先書きを潰す。
# ツール側がこのロックで読み書きサイクル全体を包む。
# プロセス間（担当者2人が別々に起動）の検知は従来どおり下のハッシュ比較が担う。
STATE_LOCK = threading.RLock()

# 直近に読み込んだ state.json のハッシュ。save_state が比較に使う。
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

    書き込む直前にファイルをもう一度読み、自分が読み込んだ時点の内容から
    変わっていたら StateConflictError を投げて中断する（指示書1-4）。
    本格的なロック機構は作らない。数字が飛ぶことだけ防ぐ。
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

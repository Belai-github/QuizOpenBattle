import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any


HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "api_history.json")
_HISTORY_LOCK = threading.Lock()


def _ensure_history_file() -> None:
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    if os.path.exists(HISTORY_PATH):
        return
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)


def _load_history() -> list[dict[str, Any]]:
    _ensure_history_file()
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _safe_json_value(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(value)


def append_api_history(entry: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    normalized_entry = {
        "id": str(entry.get("id") or uuid.uuid4()),
        "recorded_at": now.isoformat(),
        "recorded_at_ms": int(now.timestamp() * 1000),
        **{key: _safe_json_value(value) for key, value in entry.items() if key != "id"},
    }

    with _HISTORY_LOCK:
        history = _load_history()
        history.append(normalized_entry)
        tmp_path = f"{HISTORY_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, HISTORY_PATH)

    return normalized_entry

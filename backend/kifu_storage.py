import json
import os
import tempfile
import time
import uuid
from typing import Any

KIFU_DIR = os.path.join(os.path.dirname(__file__), "data", "kifu")
SCHEMA_VERSION = 1


def _ensure_dir() -> None:
    os.makedirs(KIFU_DIR, exist_ok=True)


def _kifu_file_path(kifu_id: str) -> str:
    safe_id = "".join(ch for ch in str(kifu_id or "") if ch.isalnum() or ch in {"-", "_"})
    return os.path.join(KIFU_DIR, f"{safe_id}.json")


def _atomic_write_json(file_path: str, payload: dict[str, Any]) -> None:
    _ensure_dir()
    dir_path = os.path.dirname(file_path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dir_path, delete=False) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, separators=(",", ":"))
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name
    os.replace(temp_name, file_path)


def _read_json(file_path: str) -> dict[str, Any] | None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _player_list(ids: set[str], nicknames: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for client_id in sorted(set(ids)):
        rows.append(
            {
                "client_id": client_id,
                "nickname": str(nicknames.get(client_id, "ゲスト") or "ゲスト"),
            }
        )
    return rows


def _touch_access(record: dict[str, Any]) -> None:
    access = set()
    owner_id = str(record.get("room_owner_id") or "")
    if owner_id:
        access.add(owner_id)

    questioner = record.get("questioner")
    if isinstance(questioner, dict):
        qid = str(questioner.get("client_id") or "")
        if qid:
            access.add(qid)

    participants = record.get("participants_at_start")
    if isinstance(participants, dict):
        for key in ("team_left", "team_right"):
            values = participants.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("client_id") or "")
                if cid:
                    access.add(cid)

    spectators = record.get("spectators_ever", [])
    if isinstance(spectators, list):
        for item in spectators:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("client_id") or "")
            if cid:
                access.add(cid)

    record["access_client_ids"] = sorted(access)


def begin_kifu_record(room_owner_id: str, room: dict[str, Any], nicknames: dict[str, str]) -> str:
    started_at_ms = int(time.time() * 1000)
    kifu_id = f"{room_owner_id}-{started_at_ms}-{uuid.uuid4().hex[:8]}"
    game_value = room.get("game")
    game: dict[str, Any] = game_value if isinstance(game_value, dict) else {}

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kifu_id": kifu_id,
        "room_owner_id": room_owner_id,
        "is_ai_mode": bool(room.get("is_ai_mode", False)),
        "started_at": started_at_ms,
        "finished_at": None,
        "question_text": str(room.get("question_text", "")),
        "question_length": len(str(room.get("question_text", ""))),
        "genre": str(room.get("genre", "")).strip(),
        "difficulty": int(room.get("difficulty", 0) or 0),
        "ai_model_id": str(room.get("ai_model_id", "")).strip(),
        "yakumono_indexes": sorted([int(v) for v in room.get("yakumono_indexes", set()) if isinstance(v, int)]),
        "questioner": {
            "client_id": room_owner_id,
            "nickname": str(room.get("questioner_name") or nicknames.get(room_owner_id, "ゲスト") or "ゲスト"),
        },
        "participants_at_start": {
            "team_left": _player_list(set(room.get("left_participants", set())), nicknames),
            "team_right": _player_list(set(room.get("right_participants", set())), nicknames),
        },
        "spectators_ever": _player_list(set(room.get("spectators", set())), nicknames),
        "actions": [],
        "result": {
            "game_status": str(game.get("game_status") or "playing"),
            "winner": game.get("winner"),
            "finish_reason": None,
        },
    }
    _touch_access(record)
    _atomic_write_json(_kifu_file_path(kifu_id), record)
    return kifu_id


def append_action(kifu_id: str, action: dict[str, Any]) -> None:
    file_path = _kifu_file_path(kifu_id)
    record = _read_json(file_path)
    if record is None:
        return

    actions = record.get("actions")
    if not isinstance(actions, list):
        actions = []
        record["actions"] = actions

    normalized = {
        "index": len(actions),
        "timestamp": int(action.get("timestamp") or int(time.time() * 1000)),
        "action_type": str(action.get("action_type") or ""),
        "team": str(action.get("team") or ""),
        "actor_id": str(action.get("actor_id") or ""),
        "actor_name": str(action.get("actor_name") or ""),
        "payload": action.get("payload") if isinstance(action.get("payload"), dict) else {},
    }
    actions.append(normalized)
    _atomic_write_json(file_path, record)


def resolve_latest_answer_result(kifu_id: str, team: str, answer_text: str, is_correct: bool) -> None:
    file_path = _kifu_file_path(kifu_id)
    record = _read_json(file_path)
    if record is None:
        return

    actions = record.get("actions")
    if not isinstance(actions, list):
        return

    for action in reversed(actions):
        if not isinstance(action, dict):
            continue
        if str(action.get("action_type") or "") != "answer":
            continue
        if str(action.get("team") or "") != str(team or ""):
            continue
        payload_value = action.get("payload")
        payload: dict[str, Any] = payload_value if isinstance(payload_value, dict) else {}
        if str(payload.get("answer_text") or "") != str(answer_text or ""):
            continue
        if "is_correct" in payload:
            continue
        payload["is_correct"] = bool(is_correct)
        payload["judged_at"] = int(time.time() * 1000)
        action["payload"] = payload
        _atomic_write_json(file_path, record)
        return


def touch_spectator(kifu_id: str, client_id: str, nickname: str) -> None:
    cid = str(client_id or "").strip()
    if cid == "":
        return

    file_path = _kifu_file_path(kifu_id)
    record = _read_json(file_path)
    if record is None:
        return

    spectators = record.get("spectators_ever")
    if not isinstance(spectators, list):
        spectators = []
        record["spectators_ever"] = spectators

    existing_ids = {str(item.get("client_id") or "") for item in spectators if isinstance(item, dict)}
    if cid not in existing_ids:
        spectators.append({"client_id": cid, "nickname": str(nickname or "ゲスト")})

    _touch_access(record)
    _atomic_write_json(file_path, record)


def finalize_kifu_record(kifu_id: str, room: dict[str, Any] | None, finish_reason: str) -> None:
    file_path = _kifu_file_path(kifu_id)
    record = _read_json(file_path)
    if record is None:
        return

    if record.get("finished_at") is not None:
        return

    result = record.get("result")
    if not isinstance(result, dict):
        result = {}
        record["result"] = result

    room_data: dict[str, Any] = room if isinstance(room, dict) else {}
    game_value = room_data.get("game")
    game: dict[str, Any] = game_value if isinstance(game_value, dict) else {}
    result["game_status"] = str(game.get("game_status") or room_data.get("game_state") or "finished")
    result["winner"] = game.get("winner")
    result["finish_reason"] = str(finish_reason or "finished")
    result["team_left"] = game.get("team_left") if isinstance(game.get("team_left"), dict) else {}
    result["team_right"] = game.get("team_right") if isinstance(game.get("team_right"), dict) else {}
    result["opened_char_indexes"] = sorted([int(v) for v in game.get("opened_char_indexes", set()) if isinstance(v, int)])

    record["finished_at"] = int(time.time() * 1000)
    _touch_access(record)
    _atomic_write_json(file_path, record)


def _all_records() -> list[dict[str, Any]]:
    _ensure_dir()
    records: list[dict[str, Any]] = []
    for file_name in os.listdir(KIFU_DIR):
        if not file_name.endswith(".json"):
            continue
        file_path = os.path.join(KIFU_DIR, file_name)
        record = _read_json(file_path)
        if record is None:
            continue
        records.append(record)
    return records


def _resolve_role(record: dict[str, Any], client_id: str) -> str | None:
    cid = str(client_id or "")

    def _resolve_participant_or_spectator() -> str | None:
        participants = record.get("participants_at_start")
        if isinstance(participants, dict):
            for team_key in ("team_left", "team_right"):
                values = participants.get(team_key, [])
                if not isinstance(values, list):
                    continue
                if any(isinstance(item, dict) and str(item.get("client_id") or "") == cid for item in values):
                    return "participant"

        spectators = record.get("spectators_ever", [])
        if isinstance(spectators, list):
            if any(isinstance(item, dict) and str(item.get("client_id") or "") == cid for item in spectators):
                return "spectator"

        return None

    if bool(record.get("is_ai_mode")):
        resolved_role = _resolve_participant_or_spectator()
        if resolved_role is not None:
            return resolved_role
        if cid == str(record.get("room_owner_id") or ""):
            return "questioner"
        return None

    if cid == str(record.get("room_owner_id") or ""):
        return "questioner"

    resolved_role = _resolve_participant_or_spectator()
    if resolved_role is not None:
        return resolved_role

    return None


def list_kifu_for_client(client_id: str) -> list[dict[str, Any]]:
    cid = str(client_id or "").strip()
    if cid == "":
        return []

    rows: list[dict[str, Any]] = []
    for record in _all_records():
        access = set(str(v) for v in record.get("access_client_ids", []) if isinstance(v, str))
        if cid not in access:
            continue

        role = _resolve_role(record, cid)
        questioner_value = record.get("questioner")
        questioner: dict[str, Any] = questioner_value if isinstance(questioner_value, dict) else {}
        actions_value = record.get("actions")
        actions: list[Any] = actions_value if isinstance(actions_value, list) else []
        rows.append(
            {
                "kifu_id": str(record.get("kifu_id") or ""),
                "room_owner_id": str(record.get("room_owner_id") or ""),
                "question_text": str(record.get("question_text") or ""),
                "questioner_name": str(questioner.get("nickname") or "ゲスト"),
                "started_at": int(record.get("started_at") or 0),
                "finished_at": int(record.get("finished_at") or 0),
                "action_count": len([a for a in actions if isinstance(a, dict)]),
                "your_role": role,
            }
        )

    rows.sort(key=lambda item: int(item.get("finished_at") or item.get("started_at") or 0), reverse=True)
    return rows


def get_kifu_detail_for_client(kifu_id: str, client_id: str) -> dict[str, Any] | None:
    record = _read_json(_kifu_file_path(kifu_id))
    if record is None:
        return None

    cid = str(client_id or "").strip()
    access = set(str(v) for v in record.get("access_client_ids", []) if isinstance(v, str))
    if cid not in access:
        return {}

    detail = dict(record)
    detail["your_role"] = _resolve_role(record, cid)
    return detail

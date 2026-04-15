import time


def should_append_lobby_chat_history(event_type: str | None, event_chat_type: str | None, event_room_id: str | None):
    if event_room_id:
        return False

    chat_type = str(event_chat_type or "").strip()
    event_kind = str(event_type or "").strip()
    if chat_type == "lobby":
        return True
    return event_kind in {"join", "leave", "chat"}


def append_lobby_chat_history(
    manager,
    event_type: str,
    event_message: str,
    event_chat_type: str,
    event_identity: dict | None = None,
    log_marker_id: str | None = None,
    event_timestamp: int | None = None,
):
    message = str(event_message or "").strip()
    if message == "":
        return

    stored_timestamp = int(event_timestamp) if isinstance(event_timestamp, int) and event_timestamp > 0 else int(time.time() * 1000)
    manager.lobby_chat_seq = int(manager.lobby_chat_seq) + 1
    manager.lobby_chat_history.append(
        {
            "seq": int(manager.lobby_chat_seq),
            "timestamp": stored_timestamp,
            "event_type": str(event_type or "").strip(),
            "event_message": message,
            "event_chat_type": str(event_chat_type or "").strip() or "lobby",
            "log_marker_id": str(log_marker_id or "").strip() or None,
            "event_id": str((event_identity or {}).get("event_id") or "").strip() or None,
            "event_revision": int((event_identity or {}).get("event_revision") or 1),
            "event_version": int((event_identity or {}).get("event_version") or 0),
        }
    )

    while len(manager.lobby_chat_history) > 400:
        manager.lobby_chat_history.pop(0)


def build_lobby_chat_history_snapshot(manager):
    history = manager.lobby_chat_history if isinstance(manager.lobby_chat_history, list) else []
    return [entry for entry in history if isinstance(entry, dict)]


def append_arena_chat_history(
    manager,
    room_owner_id: str,
    event_type: str,
    event_message: str,
    event_chat_type: str,
    log_marker_id: str | None = None,
    event_identity: dict | None = None,
    event_payload: dict | None = None,
    event_timestamp: int | None = None,
):
    room = manager.rooms.get(room_owner_id)
    if room is None:
        return

    if event_chat_type not in {"team-left", "team-right", "game-global"}:
        return

    message = str(event_message or "").strip()
    if message == "":
        return

    stored_timestamp = int(event_timestamp) if isinstance(event_timestamp, int) and event_timestamp > 0 else int(time.time() * 1000)
    seq = int(room.get("arena_chat_seq", 0)) + 1
    room["arena_chat_seq"] = seq
    history = room.setdefault("arena_chat_history", [])
    if not isinstance(history, list):
        history = []
        room["arena_chat_history"] = history

    history.append(
        {
            "seq": seq,
            "timestamp": stored_timestamp,
            "event_type": str(event_type or ""),
            "event_message": message,
            "event_chat_type": event_chat_type,
            "log_marker_id": str(log_marker_id or "").strip() or None,
            "event_id": str((event_identity or {}).get("event_id") or "").strip() or None,
            "event_revision": int((event_identity or {}).get("event_revision") or 1),
            "event_version": int((event_identity or {}).get("event_version") or 0),
            "event_payload": dict(event_payload) if isinstance(event_payload, dict) else {},
        }
    )

    while len(history) > 800:
        history.pop(0)


async def rebroadcast_finished_answer_logs(manager, room_owner_id: str):
    room = manager.rooms.get(room_owner_id)
    if room is None:
        return

    if room.get("finished_answer_logs_revealed"):
        return

    room["finished_answer_logs_revealed"] = True

    history = room.get("arena_chat_history") or []
    if not isinstance(history, list):
        return

    answer_event_types = {"answer_attempt", "answer_vote_request", "answer_vote_resolved"}
    recipients = {room_owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))

    sorted_history = sorted(
        [entry for entry in history if isinstance(entry, dict)],
        key=lambda entry: (int(entry.get("timestamp", 0)), int(entry.get("seq", 0))),
    )

    for entry in sorted_history:
        event_type = str(entry.get("event_type", "")).strip()
        event_chat_type = str(entry.get("event_chat_type", "")).strip()
        event_message = str(entry.get("event_message", "")).strip()
        if event_message == "" or event_type not in answer_event_types:
            continue
        if event_chat_type not in {"team-left", "team-right", "game-global"}:
            continue

        base_revision = max(1, int(entry.get("event_revision", 1) or 1))
        payload = entry.get("event_payload") if isinstance(entry.get("event_payload"), dict) else {}
        payload_map = payload if isinstance(payload, dict) else {}

        await manager.broadcast_state(
            public_info="",
            event_type=event_type,
            event_message=event_message,
            event_chat_type=event_chat_type,
            event_room_id=room_owner_id,
            event_recipient_ids=recipients,
            event_payload={
                **payload_map,
                "event_id": str(entry.get("event_id") or "").strip() or None,
                "event_revision": base_revision + 100,
                "event_timestamp": int(entry.get("timestamp") or 0),
                "reveal_phase": "finished",
                "skip_history": True,
            },
        )

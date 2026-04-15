import uuid


def derive_event_identity(
    event_room_id: str | None,
    event_type: str | None,
    event_chat_type: str | None,
    event_payload: dict | None,
    rooms: dict,
    next_room_event_id,
):
    payload = event_payload if isinstance(event_payload, dict) else {}
    event_kind = str(event_type or "").strip()
    event_scope = str(event_chat_type or "").strip() or "game-global"

    room_event_version = 1
    room_event_seq = None
    if event_room_id:
        room = rooms.get(event_room_id)
        if room is not None:
            room_event_seq = int(room.get("arena_event_id_seq", 0)) + 1
            room["arena_event_id_seq"] = room_event_seq
            room_event_version = room_event_seq

    payload_event_id = str(payload.get("event_id") or "").strip()
    vote_id = str(payload.get("vote_id") or "").strip()
    log_marker_id = str(payload.get("log_marker_id") or "").strip()

    if payload_event_id != "":
        event_id = payload_event_id
    elif vote_id != "":
        event_id = f"vote:{vote_id}"
    elif log_marker_id != "":
        event_id = f"marker:{log_marker_id}"
    elif event_room_id and room_event_seq is not None:
        event_id = f"{event_room_id}:evt:{room_event_seq}"
    elif event_room_id:
        event_id = next_room_event_id(event_room_id)
    else:
        event_id = str(uuid.uuid4())

    payload_revision = payload.get("event_revision")
    if isinstance(payload_revision, int) and payload_revision > 0:
        event_revision = payload_revision
    elif vote_id != "":
        event_revision = 2 if event_kind.endswith("_resolved") else 1
    else:
        event_revision = 1

    return {
        "event_id": event_id,
        "event_kind": event_kind,
        "event_scope": event_scope,
        "event_revision": event_revision,
        "event_version": room_event_version,
    }

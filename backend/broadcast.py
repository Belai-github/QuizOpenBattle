import time


ARENA_PROGRESS_EVENT_TYPES = {
    "game_start",
    "game_finished",
    "question",
    "room_shuffle",
    "character_opened",
    "answer_submitted",
    "full_open_settlement_start",
    "full_open_settlement_answer",
    "full_open_settlement_ready",
    "full_open_settlement_finished",
    "open_vote_request",
    "open_vote_resolved",
    "answer_attempt",
    "answer_result",
    "answer_vote_request",
    "answer_vote_resolved",
    "turn_end_vote_request",
    "turn_end_vote_resolved",
    "intentional_draw_vote_request",
    "intentional_draw_vote_resolved",
    "intentional_draw",
    "turn_changed",
    "room_reconnected",
}


def build_participants(nicknames: dict):
    participants = []
    for client_id, nickname in nicknames.items():
        participants.append({"client_id": client_id, "nickname": nickname})
    return participants


def build_rooms_summary(rooms: dict, nicknames: dict, viewer_client_id: str | None = None):
    room_summaries = []
    for owner_id, room in rooms.items():
        participant_count = len(room["left_participants"]) + len(room["right_participants"])
        room_summaries.append(
            {
                "room_owner_id": owner_id,
                "room_owner_name": nicknames.get(owner_id, "ゲスト"),
                "questioner_name": room["questioner_name"],
                "genre": str(room.get("genre") or "").strip(),
                "is_ai_room": bool(room.get("is_ai_mode")),
                "participant_count": participant_count,
                "spectator_count": len(room["spectators"]),
                "game_state": room.get("game_state", "waiting"),
                "can_join_as_participant": room.get("game_state", "waiting") == "waiting",
                "is_owner": viewer_client_id == owner_id,
            }
        )
    return room_summaries


def resolve_event_timestamp(event_payload: dict | None):
    payload_event_timestamp = None
    if isinstance(event_payload, dict):
        raw_event_timestamp = event_payload.get("event_timestamp")
        if isinstance(raw_event_timestamp, int) and raw_event_timestamp > 0:
            payload_event_timestamp = raw_event_timestamp
        elif isinstance(raw_event_timestamp, str):
            raw_event_timestamp = raw_event_timestamp.strip()
            if raw_event_timestamp.isdigit():
                parsed_event_timestamp = int(raw_event_timestamp)
                if parsed_event_timestamp > 0:
                    payload_event_timestamp = parsed_event_timestamp
    return payload_event_timestamp or int(time.time() * 1000)


def resolve_log_marker_id(event_payload: dict | None):
    if not isinstance(event_payload, dict):
        return None

    payload_marker = event_payload.get("log_marker_id") or event_payload.get("vote_id")
    payload_marker_text = str(payload_marker or "").strip()
    if payload_marker_text == "":
        return None
    return payload_marker_text


def resolve_arena_history_chat_type(event_type: str | None, event_chat_type: str | None):
    if event_chat_type in {"team-left", "team-right", "game-global"}:
        return event_chat_type
    if event_type in {"room_entry", "room_exit"}:
        return "game-global"
    if event_type in ARENA_PROGRESS_EVENT_TYPES:
        return "game-global"
    return None


def build_ws_response(
    *,
    public_info: str,
    private_info: str,
    participants: list,
    rooms: list,
    current_room: dict | None,
    lobby_chat_history: list,
    ai_question_generation_active: bool,
    ai_question_generation_owner_id: str | None,
    response_event_type: str | None,
    response_event_message: str | None,
    response_event_chat_type: str | None,
    event_room_id: str | None,
    target_screen: str | None,
    response_event_payload: dict | None,
    is_event_recipient: bool,
    history_message: str,
    event_identity: dict,
    event_timestamp: int,
):
    return {
        "public_info": public_info,
        "private_info": private_info,
        "participants": participants,
        "rooms": rooms,
        "current_room": current_room,
        "lobby_chat_history": lobby_chat_history,
        "ai_question_generation_active": ai_question_generation_active,
        "ai_question_generation_owner_id": ai_question_generation_owner_id,
        "event_type": response_event_type,
        "event_message": response_event_message,
        "event_chat_type": response_event_chat_type,
        "event_room_id": event_room_id,
        "target_screen": target_screen,
        "event_payload": response_event_payload,
        "event_view": (
            {
                "display_message": response_event_message,
                "masked": bool(response_event_message is not None and response_event_message != history_message),
            }
            if is_event_recipient
            else None
        ),
        "event_id": event_identity["event_id"] if is_event_recipient else None,
        "event_kind": event_identity["event_kind"] if is_event_recipient else None,
        "event_scope": event_identity["event_scope"] if is_event_recipient else None,
        "event_revision": event_identity["event_revision"] if is_event_recipient else None,
        "event_version": event_identity["event_version"] if is_event_recipient else None,
        "event_timestamp": event_timestamp if is_event_recipient else None,
    }

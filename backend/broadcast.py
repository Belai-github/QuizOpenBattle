import json
import time


ARENA_PROGRESS_EVENT_TYPES = {
    "game_start",
    "game_finished",
    "expected_answer_reveal",
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


async def send_private_info(
    manager,
    client_id: str,
    message: str,
    target_screen: str | None = None,
    event_type: str = "private_notice",
):
    ws = manager.active_connections.get(client_id)
    if ws is None:
        return

    response = {
        "public_info": "",
        "private_info": message,
        "participants": manager.build_participants(),
        "rooms": manager.build_rooms_summary(client_id),
        "current_room": manager.build_current_room_for_client(client_id),
        "lobby_chat_history": manager._build_lobby_chat_history_snapshot(),
        "event_type": event_type,
        "event_message": None,
        "event_chat_type": None,
        "event_room_id": None,
        "target_screen": target_screen,
    }
    await ws.send_text(json.dumps(response))


async def broadcast_state(
    manager,
    public_info: str,
    private_map: dict | None = None,
    event_type: str | None = None,
    event_message: str | None = None,
    event_chat_type: str | None = None,
    event_room_id: str | None = None,
    target_screen: str | None = None,
    event_recipient_ids: set[str] | None = None,
    event_payload: dict | None = None,
):
    history_message = str(event_message or public_info or "").strip()
    event_timestamp = resolve_event_timestamp(event_payload)
    event_identity = manager._derive_event_identity(
        event_room_id=event_room_id,
        event_type=event_type,
        event_chat_type=event_chat_type,
        event_payload=event_payload,
    )
    log_marker_id = resolve_log_marker_id(event_payload)

    skip_history = isinstance(event_payload, dict) and bool(event_payload.get("skip_history"))
    if history_message and not skip_history and manager._should_append_lobby_chat_history(event_type, event_chat_type, event_room_id):
        manager._append_lobby_chat_history(
            event_type=event_type or "",
            event_message=history_message,
            event_chat_type=str(event_chat_type or "").strip() or "lobby",
            event_identity=event_identity,
            log_marker_id=log_marker_id,
            event_timestamp=event_timestamp,
        )

    if event_room_id and history_message and not skip_history:
        arena_history_chat_type = resolve_arena_history_chat_type(event_type, event_chat_type)
        if arena_history_chat_type is not None:
            manager._append_arena_chat_history(
                event_room_id,
                event_type or "",
                history_message,
                arena_history_chat_type,
                log_marker_id,
                event_identity=event_identity,
                event_payload=event_payload,
                event_timestamp=event_timestamp,
            )

    participants = manager.build_participants()
    for client_id, ws in manager.active_connections.items():
        rooms = manager.build_rooms_summary(client_id)
        current_room = manager.build_current_room_for_client(client_id)
        private_info = ""
        if private_map is not None:
            private_info = private_map.get(client_id, "")

        is_event_recipient = event_recipient_ids is None or client_id in event_recipient_ids
        response_event_type = event_type if is_event_recipient else None
        response_event_message = (
            manager._resolve_event_message_for_client(
                current_room,
                event_type,
                event_chat_type,
                history_message,
                event_payload,
            )
            if is_event_recipient
            else None
        )
        response_event_payload = (
            manager._resolve_event_payload_for_client(
                current_room,
                event_type,
                event_chat_type,
                event_payload,
            )
            if is_event_recipient
            else None
        )
        response_event_chat_type = event_chat_type if is_event_recipient else None

        response = build_ws_response(
            public_info=public_info,
            private_info=private_info,
            participants=participants,
            rooms=rooms,
            current_room=current_room,
            lobby_chat_history=manager._build_lobby_chat_history_snapshot(),
            ai_question_generation_active=manager.ai_question_generation_active,
            ai_question_generation_owner_id=manager.ai_question_generation_owner_id,
            response_event_type=response_event_type,
            response_event_message=response_event_message,
            response_event_chat_type=response_event_chat_type,
            event_room_id=event_room_id,
            target_screen=target_screen,
            response_event_payload=response_event_payload,
            is_event_recipient=is_event_recipient,
            history_message=history_message,
            event_identity=event_identity,
            event_timestamp=event_timestamp,
        )
        await ws.send_text(json.dumps(response))

    should_reveal_finished_answers = event_type == "game_finished" and bool(event_room_id) and not (isinstance(event_payload, dict) and bool(event_payload.get("skip_finished_answer_reveal")))
    if should_reveal_finished_answers:
        await manager._rebroadcast_finished_answer_logs(str(event_room_id))

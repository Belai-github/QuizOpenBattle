import re


def mask_answer_text_for_viewer(message: str):
    text = str(message or "")
    if text == "":
        return ""
    return re.sub(r"が「[^」]*」と", "が", text)


def resolve_event_message_for_client(
    current_room: dict | None,
    event_type: str | None,
    event_chat_type: str | None,
    event_message: str,
    event_payload: dict | None,
):
    message = str(event_message or "").strip()
    if message == "":
        return ""

    if not isinstance(current_room, dict):
        return message

    room_state = str(current_room.get("game_state", "waiting") or "waiting")
    viewer_role = str(current_room.get("chat_role", "") or "")
    viewer_type = str(current_room.get("role", "") or "")

    if room_state != "playing" or viewer_type != "participant" or viewer_role not in {"team-left", "team-right"}:
        return message

    event_kind = str(event_type or "").strip()
    if event_kind not in {"answer_attempt", "answer_vote_request", "answer_vote_resolved"}:
        return message

    payload = event_payload if isinstance(event_payload, dict) else {}
    source_team = str(payload.get("team") or event_chat_type or "").strip()
    game = current_room.get("game")
    left_reveal_window = isinstance(game, dict) and bool(game.get("left_correct_waiting")) and viewer_role == "team-left"
    if left_reveal_window and source_team == "team-right":
        return message

    if source_team in {"team-left", "team-right"} and source_team != viewer_role:
        return mask_answer_text_for_viewer(message)

    return message


def resolve_event_payload_for_client(
    current_room: dict | None,
    event_type: str | None,
    event_chat_type: str | None,
    event_payload: dict | None,
):
    if not isinstance(event_payload, dict):
        return event_payload

    payload = dict(event_payload)
    event_kind = str(event_type or "").strip()
    if event_kind not in {"answer_attempt", "answer_vote_request", "answer_vote_resolved"}:
        return payload

    if str(payload.get("reveal_phase") or "").strip() == "finished":
        return payload

    if not isinstance(current_room, dict):
        return payload

    room_state = str(current_room.get("game_state", "waiting") or "waiting")
    if room_state != "playing":
        return payload

    viewer_type = str(current_room.get("role", "") or "")
    viewer_role = str(current_room.get("chat_role", "") or "")
    source_team = str(payload.get("team") or event_chat_type or "").strip()
    game = current_room.get("game")
    left_reveal_window = isinstance(game, dict) and bool(game.get("left_correct_waiting")) and viewer_role == "team-left"

    if viewer_type == "owner" or viewer_role == "questioner":
        return payload

    if viewer_type == "participant" and left_reveal_window and source_team == "team-right":
        return payload

    if viewer_type == "spectator" or viewer_role == "spectator":
        payload.pop("answer_text", None)
        return payload

    if viewer_type == "participant" and viewer_role in {"team-left", "team-right"} and source_team in {"team-left", "team-right"} and source_team != viewer_role:
        payload.pop("answer_text", None)

    return payload

import random


def remove_client_from_all_rooms(rooms: dict, client_id: str):
    for room in rooms.values():
        room["left_participants"].discard(client_id)
        room["right_participants"].discard(client_id)
        room["spectators"].discard(client_id)


def resolve_client_room_context(rooms: dict, client_id: str):
    for owner_id, room in rooms.items():
        if owner_id == client_id:
            return {
                "room_owner_id": owner_id,
                "room": room,
                "role": "owner",
                "chat_role": "questioner",
            }

        if client_id in room["left_participants"]:
            return {
                "room_owner_id": owner_id,
                "room": room,
                "role": "participant",
                "chat_role": "team-left",
            }

        if client_id in room["right_participants"]:
            return {
                "room_owner_id": owner_id,
                "room": room,
                "role": "participant",
                "chat_role": "team-right",
            }

        if client_id in room["spectators"]:
            return {
                "room_owner_id": owner_id,
                "room": room,
                "role": "spectator",
                "chat_role": "spectator",
            }

    return None


def build_current_room_for_client(rooms: dict, nicknames: dict, client_id: str):
    ctx = resolve_client_room_context(rooms, client_id)
    if ctx is None:
        return None

    owner_id = ctx["room_owner_id"]
    room = ctx["room"]
    chat_role = ctx["chat_role"]

    left_participants = []
    for pid in room["left_participants"]:
        left_participants.append(
            {
                "client_id": pid,
                "nickname": nicknames.get(pid, "ゲスト"),
            }
        )

    right_participants = []
    for pid in room["right_participants"]:
        right_participants.append(
            {
                "client_id": pid,
                "nickname": nicknames.get(pid, "ゲスト"),
            }
        )

    spectators = []
    for sid in room["spectators"]:
        spectators.append(
            {
                "client_id": sid,
                "nickname": nicknames.get(sid, "ゲスト"),
            }
        )

    raw_question_text = str(room.get("question_text", ""))
    question_text_for_client = raw_question_text if chat_role == "questioner" else ""

    return {
        "room_owner_id": owner_id,
        "questioner_id": owner_id,
        "questioner_name": room["questioner_name"],
        "question_text": question_text_for_client,
        "question_length": len(raw_question_text),
        "game_state": room.get("game_state", "waiting"),
        "role": ctx["role"],
        "chat_role": chat_role,
        "left_participants": left_participants,
        "right_participants": right_participants,
        "spectators": spectators,
    }


def apply_join_room(rooms: dict, client_id: str, room_owner_id: str, role: str):
    room = rooms.get(room_owner_id)
    if room is None:
        return {"ok": False, "error": "部屋が見つかりません。"}

    if client_id == room_owner_id:
        return {
            "ok": True,
            "role_name": "出題者",
            "entry_message": "あなたの出題部屋に入室しました。",
            "target_screen": "game_arena",
            "event_role_name": None,
        }

    remove_client_from_all_rooms(rooms, client_id)
    converted_to_spectator = False

    final_role = role
    if final_role == "participant" and room.get("game_state", "waiting") == "playing":
        final_role = "spectator"
        converted_to_spectator = True

    if final_role == "participant":
        left_count = len(room["left_participants"])
        right_count = len(room["right_participants"])

        if left_count == right_count:
            side = random.choice(["left", "right"])
        elif left_count < right_count:
            side = "left"
        else:
            side = "right"

        if side == "left":
            room["left_participants"].add(client_id)
        else:
            room["right_participants"].add(client_id)
        role_name = "参加者"
    else:
        room["spectators"].add(client_id)
        role_name = "観戦者"

    entry_message = f"{room['questioner_name']} の部屋に{role_name}として入りました。"
    if converted_to_spectator:
        entry_message = "ゲーム中のため参加では入室できません。\n" f"{room['questioner_name']} の部屋に観戦者として入りました。"

    return {
        "ok": True,
        "role_name": role_name,
        "entry_message": entry_message,
        "target_screen": "game_arena",
        "event_role_name": role_name,
    }


def apply_start_game(rooms: dict, client_id: str):
    room = rooms.get(client_id)
    if room is None:
        return {"ok": False, "error": "ゲーム開始は出題者のみ実行できます。"}

    if room.get("game_state", "waiting") == "playing":
        return {"ok": False, "error": "すでにゲームは開始しています。"}

    if not room["left_participants"] or not room["right_participants"]:
        return {"ok": False, "error": "先攻・後攻の参加者がそろってから開始してください。"}

    room["game_state"] = "playing"
    return {"ok": True, "questioner_name": room["questioner_name"]}


def apply_shuffle_participants(rooms: dict, client_id: str):
    room = rooms.get(client_id)
    if room is None:
        return {"ok": False, "error": "参加者シャッフルは出題者のみ実行できます。"}

    if room.get("game_state", "waiting") != "waiting":
        return {"ok": False, "error": "ゲーム開始後は参加者シャッフルできません。"}

    participants = list(set(room["left_participants"]) | set(room["right_participants"]))
    if len(participants) < 2:
        return {"ok": False, "error": "参加者が2人以上いるときにシャッフルできます。"}

    random.shuffle(participants)
    odd_to_left = random.choice([True, False])

    new_left = set()
    new_right = set()
    for idx, pid in enumerate(participants, start=1):
        is_odd = idx % 2 == 1
        assign_left = is_odd if odd_to_left else not is_odd
        if assign_left:
            new_left.add(pid)
        else:
            new_right.add(pid)

    room["left_participants"] = new_left
    room["right_participants"] = new_right
    return {"ok": True, "questioner_name": room["questioner_name"]}


def apply_exit_room(rooms: dict, client_id: str):
    if client_id in rooms:
        room = rooms.pop(client_id)
        affected_client_ids = set(room["left_participants"]) | set(room["right_participants"]) | set(room["spectators"])
        return {
            "owner_closed": True,
            "affected_client_ids": affected_client_ids,
        }

    remove_client_from_all_rooms(rooms, client_id)
    return {
        "owner_closed": False,
        "affected_client_ids": set(),
    }


def apply_create_question_room(rooms: dict, nicknames: dict, player_id: str, payload: dict):
    if player_id in rooms:
        return {"ok": False, "error": "同時に出題できる問題は1つまでです。"}

    actor_name = nicknames.get(player_id, "相手")
    question_text = str(payload.get("question_text", payload.get("content", ""))).strip()
    if question_text == "":
        question_text = "（空欄）"

    rooms[player_id] = {
        "owner_id": player_id,
        "question_text": question_text,
        "questioner_name": actor_name,
        "game_state": "waiting",
        "left_participants": set(),
        "right_participants": set(),
        "spectators": set(),
    }

    remove_client_from_all_rooms(rooms, player_id)
    return {"ok": True, "actor_name": actor_name}


def resolve_chat_recipients(room_owner_id: str, room: dict, sender_chat_role: str | None, chat_type: str):
    room_state = room.get("game_state", "waiting")

    role_to_ids = {
        "questioner": {room_owner_id},
        "team-left": set(room["left_participants"]),
        "team-right": set(room["right_participants"]),
        "spectator": set(room["spectators"]),
    }

    if room_state == "waiting":
        if chat_type != "game-global":
            return {"ok": False, "error": "ゲーム開始前は全体チャットのみ利用できます。"}

        event_recipient_ids = set()
        for ids in role_to_ids.values():
            event_recipient_ids |= ids
        return {"ok": True, "event_recipient_ids": event_recipient_ids}

    sendable_roles_by_type = {
        "team-left": {"team-left", "questioner"},
        "team-right": {"team-right", "questioner"},
        "spectator": {"spectator", "questioner"},
    }
    readable_roles_by_type = {
        "team-left": {"team-left", "questioner", "spectator"},
        "team-right": {"team-right", "questioner", "spectator"},
        "spectator": {"spectator", "questioner"},
    }

    if chat_type not in sendable_roles_by_type:
        return {"ok": False, "error": "未対応のチャット種別です。"}

    if sender_chat_role not in sendable_roles_by_type[chat_type]:
        return {"ok": False, "error": "このチャット欄では発言できません。"}

    event_recipient_ids = set()
    for role_name in readable_roles_by_type[chat_type]:
        event_recipient_ids |= role_to_ids.get(role_name, set())

    return {"ok": True, "event_recipient_ids": event_recipient_ids}

import random
import time
import unicodedata


QUESTION_MASK_CHAR = "■"
QUESTION_TEXT_MAX_LENGTH = 100


def _normalize_log_marker_id(raw_value):
    if raw_value is None:
        return None

    marker = str(raw_value).strip()
    if marker == "":
        return None

    if marker.lower() in {"none", "null", "undefined"}:
        return None

    return marker


def _normalized_question_chars(text: str):
    normalized_text = unicodedata.normalize("NFC", str(text or ""))
    return [ch for ch in normalized_text if ch not in {"\n", "\r"}]


def _build_visible_question_text(normalized_chars: list[str], game: dict | None, chat_role: str):
    if not normalized_chars:
        return ""

    if chat_role == "questioner":
        return "".join(normalized_chars)

    # 対戦終了後は全員に全文を公開する。
    if game and game.get("game_status") == "finished":
        return "".join(normalized_chars)

    if chat_role == "spectator" and game and game.get("game_status") == "playing":
        return "".join(normalized_chars)

    masked = [QUESTION_MASK_CHAR] * len(normalized_chars)
    if not game or game.get("game_status") != "playing":
        return "".join(masked)

    opened_by_team = game.get("opened_by_team", {})
    for idx, ch in enumerate(normalized_chars):
        owner = opened_by_team.get(idx)
        if owner == "yakumono" or owner == chat_role:
            masked[idx] = ch

    return "".join(masked)


def _sync_room_game_state_with_game_status(room: dict):
    game = room.get("game") or {}
    game_status = game.get("game_status")
    if game_status == "finished":
        room["game_state"] = "finished"
    elif game_status == "playing":
        room["game_state"] = "playing"


def remove_client_from_all_rooms(rooms: dict, client_id: str):
    for room in rooms.values():
        room["left_participants"].discard(client_id)
        room["right_participants"].discard(client_id)
        room["spectators"].discard(client_id)
        pending_disconnects = room.get("pending_disconnects")
        if isinstance(pending_disconnects, dict):
            pending_disconnects.pop(client_id, None)


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

    _sync_room_game_state_with_game_status(room)

    pending_disconnects_raw = room.get("pending_disconnects", {})
    now = time.time()

    def _resolve_display_name(target_client_id: str):
        if target_client_id in nicknames:
            return nicknames.get(target_client_id, "ゲスト")

        if isinstance(pending_disconnects_raw, dict):
            pending_info = pending_disconnects_raw.get(target_client_id)
            if isinstance(pending_info, dict):
                return str(pending_info.get("nickname") or "ゲスト")

        return "ゲスト"

    left_participants = []
    for pid in room["left_participants"]:
        left_participants.append(
            {
                "client_id": pid,
                "nickname": _resolve_display_name(pid),
            }
        )

    right_participants = []
    for pid in room["right_participants"]:
        right_participants.append(
            {
                "client_id": pid,
                "nickname": _resolve_display_name(pid),
            }
        )

    spectators = []
    for sid in room["spectators"]:
        spectators.append(
            {
                "client_id": sid,
                "nickname": _resolve_display_name(sid),
            }
        )

    pending_disconnects = []
    if isinstance(pending_disconnects_raw, dict):
        for pending_id, pending_info in pending_disconnects_raw.items():
            if not isinstance(pending_info, dict):
                continue

            expires_at = float(pending_info.get("expires_at") or 0)
            if expires_at <= now:
                continue

            team = str(pending_info.get("team") or "")
            if team not in {"team-left", "team-right"}:
                continue

            pending_disconnects.append(
                {
                    "client_id": pending_id,
                    "nickname": _resolve_display_name(pending_id),
                    "team": team,
                    "expires_at": expires_at,
                }
            )
    pending_disconnects.sort(key=lambda item: item.get("expires_at", 0))

    raw_question_text = str(room.get("question_text", ""))
    normalized_chars = _normalized_question_chars(raw_question_text)
    normalized_text = "".join(normalized_chars)
    question_text_for_client = normalized_text if chat_role == "questioner" else ""

    # ゲーム状態をJSON シリアライズ可能な形式に変換
    game_state = room.get("game")
    if game_state:
        game_state = {
            "current_turn_team": game_state.get("current_turn_team"),
            "game_status": game_state.get("game_status"),
            "winner": game_state.get("winner"),
            "is_judging_answer": game_state.get("pending_answer_judgement") is not None,
            "team_left": game_state.get("team_left", {}),
            "team_right": game_state.get("team_right", {}),
            "opened_char_indexes": sorted(list(game_state.get("opened_char_indexes", set()))),
            "opened_by_team": {str(k): v for k, v in game_state.get("opened_by_team", {}).items()},
        }

    question_visible_text = _build_visible_question_text(normalized_chars, room.get("game"), chat_role)

    arena_chat_history = []
    pre_game_global_chat_history = []
    room_state = room.get("game_state", "waiting")
    raw_history = room.get("arena_chat_history") or []
    raw_count = 0
    sorted_count = 0
    if isinstance(raw_history, list):
        readable_roles_by_type = {
            "team-left": {"team-left", "questioner", "spectator"},
            "team-right": {"team-right", "questioner", "spectator"},
            "game-global": {"team-left", "team-right", "questioner", "spectator"},
        }

        raw_count = len(raw_history)
        sorted_history = sorted(
            [entry for entry in raw_history if isinstance(entry, dict)],
            key=lambda entry: (int(entry.get("timestamp", 0)), int(entry.get("seq", 0))),
        )
        sorted_count = len(sorted_history)

        for entry in sorted_history:
            event_chat_type = str(entry.get("event_chat_type", "")).strip()
            event_type = str(entry.get("event_type", "")).strip()
            event_message = str(entry.get("event_message", "")).strip()
            if event_message == "":
                continue

            readable_roles = readable_roles_by_type.get(event_chat_type)
            if not readable_roles or chat_role not in readable_roles:
                continue

            if room_state == "playing" and ctx["role"] == "participant" and event_type == "chat":
                continue

            arena_chat_history.append(
                {
                    "seq": int(entry.get("seq", 0)),
                    "timestamp": int(entry.get("timestamp", 0)),
                    "event_type": event_type,
                    "event_message": event_message,
                    "event_chat_type": event_chat_type,
                    "log_marker_id": _normalize_log_marker_id(entry.get("log_marker_id")),
                }
            )
    print(f"[DEBUG] build_current_room_for_client: raw_count={raw_count}, sorted_count={sorted_count}, final_arena_history_count={len(arena_chat_history)}, role={ctx['role']}, room_state={room_state}")
    if room_state == "playing" and ctx["role"] == "participant":
        pre_game_global_chat_history = []

    return {
        "room_owner_id": owner_id,
        "questioner_id": owner_id,
        "questioner_name": room["questioner_name"],
        "question_text": question_text_for_client,
        "question_visible_text": question_visible_text,
        "question_length": len(normalized_chars),
        "yakumono_indexes": sorted(list(room.get("yakumono_indexes", set()))),
        "game_state": room.get("game_state", "waiting"),
        "game": game_state,
        "role": ctx["role"],
        "chat_role": chat_role,
        "left_participants": left_participants,
        "right_participants": right_participants,
        "spectators": spectators,
        "pending_disconnects": pending_disconnects,
        "arena_chat_history": arena_chat_history,
        "pre_game_global_chat_history": pre_game_global_chat_history,
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
    if final_role == "participant" and room.get("game_state", "waiting") != "waiting":
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


def _sanitize_selected_indexes(raw_indexes, max_length: int):
    if not isinstance(raw_indexes, list):
        return set()

    selected = set()
    for value in raw_indexes:
        if isinstance(value, bool):
            continue
        if not isinstance(value, int):
            continue
        if 0 <= value < max_length:
            selected.add(value)
    return selected


def apply_start_game(rooms: dict, client_id: str, payload: dict | None = None):
    room = rooms.get(client_id)
    if room is None:
        return {"ok": False, "error": "ゲーム開始は出題者のみ実行できます。"}

    if room.get("game_state", "waiting") == "playing":
        return {"ok": False, "error": "すでにゲームは開始しています。"}

    if not room["left_participants"] or not room["right_participants"]:
        return {"ok": False, "error": "先攻・後攻の参加者がそろってから開始してください。"}

    payload = payload or {}
    question_length = len(_normalized_question_chars(room.get("question_text", "")))
    selected_indexes = _sanitize_selected_indexes(payload.get("selected_char_indexes"), question_length)
    room["yakumono_indexes"] = selected_indexes

    room["game_state"] = "playing"

    # ゲーム状態の初期化
    room["game"] = {
        "current_turn_team": "team-left",  # 先攻から開始
        "game_status": "playing",  # "playing" | "finished"
        "winner": None,  # None | "team-left" | "team-right"
        "pending_answer_judgement": None,  # {team, answer_text, answerer_id} | None
        "left_correct_waiting": False,  # 先攻正解後、後攻の最終ターン待ち
        # チームごとのアクション権
        "team_left": {
            "action_points": 1,  # ターン中のアクション権
            "bonus_action_points": 0,  # ＋アクション権（持ち越し可能）
            "correct_answer": None,  # False=誤答, True=正解, None=未답
        },
        "team_right": {
            "action_points": 0,
            "bonus_action_points": 0,
            "correct_answer": None,
        },
        # オープン状態（ゲーム全体で共有）
        "opened_char_indexes": set(),  # どの文字がオープンされたか
        "opened_by_team": {},  # インデックス -> "team-left" | "team-right" | "yakumono"
    }

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

    if len(_normalized_question_chars(question_text)) > QUESTION_TEXT_MAX_LENGTH:
        return {
            "ok": False,
            "error": f"問題文は{QUESTION_TEXT_MAX_LENGTH}文字以内で入力してください。",
        }

    rooms[player_id] = {
        "owner_id": player_id,
        "question_text": question_text,
        "yakumono_indexes": set(),
        "questioner_name": actor_name,
        "game_state": "waiting",
        "left_participants": set(),
        "right_participants": set(),
        "spectators": set(),
        "pending_disconnects": {},
        "arena_chat_history": [],
        "arena_chat_seq": 0,
        "pre_game_global_chat_history": [],
        "pre_game_global_chat_seq": 0,
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

    # 全体チャットは待機中・終了後は全員、対戦中は出題者/観戦者のみ送受信可能
    if chat_type == "game-global":
        if room_state == "playing":
            if sender_chat_role not in {"questioner", "spectator"}:
                return {"ok": False, "error": "対戦中の全体チャットは出題者/観戦者のみ利用できます。"}

            event_recipient_ids = role_to_ids["questioner"] | role_to_ids["spectator"]
            return {"ok": True, "event_recipient_ids": event_recipient_ids}
        elif room_state != "finished":
            return {"ok": False, "error": "全体チャットを利用できない状態です。"}

        event_recipient_ids = set()
        for ids in role_to_ids.values():
            event_recipient_ids |= ids
        return {"ok": True, "event_recipient_ids": event_recipient_ids}

    sendable_roles_by_type = {
        "team-left": {"team-left", "questioner"},
        "team-right": {"team-right", "questioner"},
    }
    readable_roles_by_type = {
        "team-left": {"team-left", "questioner", "spectator"},
        "team-right": {"team-right", "questioner", "spectator"},
    }

    if chat_type not in sendable_roles_by_type:
        return {"ok": False, "error": "未対応のチャット種別です。"}

    if sender_chat_role not in sendable_roles_by_type[chat_type]:
        return {"ok": False, "error": "このチャット欄では発言できません。"}

    event_recipient_ids = set()
    for role_name in readable_roles_by_type[chat_type]:
        event_recipient_ids |= role_to_ids.get(role_name, set())

    return {"ok": True, "event_recipient_ids": event_recipient_ids}


# ==================== ゲーム中のアクション処理 ====================


def _team_state_key(team: str):
    if team == "team-left":
        return "team_left"
    if team == "team-right":
        return "team_right"
    return ""


def _is_no_action_remaining(team_state: dict):
    return team_state.get("action_points", 0) <= 0 and team_state.get("bonus_action_points", 0) <= 0


def _consume_one_action_point(team_state: dict):
    total_actions = team_state.get("action_points", 0) + team_state.get("bonus_action_points", 0)
    if total_actions <= 0:
        return False

    if team_state.get("action_points", 0) > 0:
        team_state["action_points"] -= 1
    else:
        team_state["bonus_action_points"] -= 1

    return True


def apply_open_character(room: dict, team: str, char_index: int):
    """
    指定されたチームが文字をオープンします。

    Args:
        room: ゲームルーム
        team: "team-left" | "team-right"
        char_index: オープンする文字のインデックス

    Returns:
        {"ok": bool, "error": str | None, "is_yakumono": bool}
    """
    game = room.get("game", {})

    # ゲーム中かどうか確認
    if game.get("game_status") != "playing":
        return {"ok": False, "error": "ゲーム中ではありません。"}

    if game.get("pending_answer_judgement") is not None:
        return {"ok": False, "error": "正誤判定中は行動できません。"}

    # ターンが正しいかどうか確認
    if game.get("current_turn_team") != team:
        return {"ok": False, "error": "あなたのターンではありません。"}

    # アクション権があるかどうか確認
    team_state = game.get(_team_state_key(team), {})
    total_actions = team_state.get("action_points", 0) + team_state.get("bonus_action_points", 0)
    if total_actions <= 0:
        return {"ok": False, "error": "アクション権がありません。"}

    # インデックスが有効か確認
    question_length = len(_normalized_question_chars(room.get("question_text", "")))
    if not (0 <= char_index < question_length):
        return {"ok": False, "error": "無効な文字インデックスです。"}

    # すでにオープンされているか確認
    if char_index in game.get("opened_char_indexes", set()):
        return {"ok": False, "error": "すでにオープンされています。"}

    # 文字をオープン
    game["opened_char_indexes"].add(char_index)

    # 約物かどうかを判定
    is_yakumono = char_index in room.get("yakumono_indexes", set())

    if is_yakumono:
        # 約物の場合：相手にも公開、アクション権を1獲得
        game["opened_by_team"][char_index] = "yakumono"
        team_state["action_points"] += 1
    else:
        # 通常の文字：自分だけに公開
        game["opened_by_team"][char_index] = team

    # アクション権を消費
    _consume_one_action_point(team_state)

    if _is_no_action_remaining(team_state):
        # 先攻正解後の後攻ターンで正解できなければ先攻勝利
        if team == "team-right" and game.get("left_correct_waiting"):
            game["winner"] = "team-left"
            game["game_status"] = "finished"
            game["left_correct_waiting"] = False
        else:
            yield_turn(game)

    _sync_room_game_state_with_game_status(room)

    return {
        "ok": True,
        "is_yakumono": is_yakumono,
        "opened_char_indexes": sorted(list(game["opened_char_indexes"])),
    }


def apply_submit_answer(room: dict, team: str, is_correct: bool):
    """
    指定されたチームが解答を提出します。

    Args:
        room: ゲームルーム
        team: "team-left" | "team-right"
        is_correct: 解答が正解かどうかの判定（出題者が判定）

    Returns:
        {"ok": bool, "error": str | None, "game_status": str, "winner": str | None}
    """
    game = room.get("game", {})

    # ゲーム中かどうか確認
    if game.get("game_status") != "playing":
        return {"ok": False, "error": "ゲーム中ではありません。"}

    if game.get("pending_answer_judgement") is not None:
        return {"ok": False, "error": "正誤判定中です。"}

    # ターンが正しいかどうか確認
    if game.get("current_turn_team") != team:
        return {"ok": False, "error": "あなたのターンではありません。"}

    team_state = game.get(_team_state_key(team), {})
    other_team = "team-right" if team == "team-left" else "team-left"
    other_team_state = game.get(_team_state_key(other_team), {})

    if not _consume_one_action_point(team_state):
        return {"ok": False, "error": "アクション権がありません。"}

    if is_correct:
        # 正解
        team_state["correct_answer"] = True

        # 先攻が正解した場合、後攻の最終ターンへ
        if team == "team-left":
            game["left_correct_waiting"] = True
            if game.get("game_status") == "playing":
                yield_turn(game)
        else:
            # 後攻が正解した場合、その時点で後攻勝利。
            # ただし先攻正解待ち中なら引き分け。
            if game.get("left_correct_waiting"):
                game["winner"] = "draw"
            else:
                game["winner"] = "team-right"
            game["game_status"] = "finished"
            game["left_correct_waiting"] = False
    else:
        # 誤答
        team_state["correct_answer"] = False
        # 相手に＋アクション権を付与
        other_team_state["bonus_action_points"] += 1

        # 先攻正解後の後攻誤答はその時点で先攻勝利
        if team == "team-right" and game.get("left_correct_waiting"):
            game["winner"] = "team-left"
            game["game_status"] = "finished"
            game["left_correct_waiting"] = False
        elif _is_no_action_remaining(team_state):
            # 誤答したチームがアクション権をまだ持っていれば、ターンは継続
            # アクション権がなければ、ターン終了時に次のターンへ（相手にターンを譲る）
            yield_turn(game)

    _sync_room_game_state_with_game_status(room)

    return {
        "ok": True,
        "game_status": game.get("game_status"),
        "winner": game.get("winner"),
    }


def apply_end_turn(room: dict, team: str):
    """
    指定されたチームがターンを終了します。
    """
    game = room.get("game", {})

    # ゲーム中かどうか確認
    if game.get("game_status") != "playing":
        return {"ok": False, "error": "ゲーム中ではありません。"}

    if game.get("pending_answer_judgement") is not None:
        return {"ok": False, "error": "正誤判定中は行動できません。"}

    # ターンが正しいかどうか確認
    if game.get("current_turn_team") != team:
        return {"ok": False, "error": "あなたのターンではありません。"}

    # 通常アクション権はターン終了時に持ち越さない
    team_state = game.get(_team_state_key(team), {})
    team_state["action_points"] = 0

    # 先攻正解後の後攻ターンで正解できなければ先攻勝利
    if team == "team-right" and game.get("left_correct_waiting"):
        game["winner"] = "team-left"
        game["game_status"] = "finished"
        game["left_correct_waiting"] = False
        _sync_room_game_state_with_game_status(room)
        return {
            "ok": True,
            "current_turn_team": game.get("current_turn_team"),
        }

    # 次のターンへ
    yield_turn(game)

    # 新しいターン側の通常アクション権付与は yield_turn 側で行う
    new_turn_team = game.get("current_turn_team")

    _sync_room_game_state_with_game_status(room)

    return {
        "ok": True,
        "current_turn_team": new_turn_team,
    }


def yield_turn(game: dict):
    """ターンを相手に譲渡します。"""
    current = str(game.get("current_turn_team") or "")
    current_team_key = _team_state_key(current)
    if current_team_key in game:
        game[current_team_key]["action_points"] = 0

    next_team = "team-right" if current == "team-left" else "team-left"
    game["current_turn_team"] = next_team

    # 次ターン開始時、通常アクション権を1配る（＋アクション権は持ち越し）
    next_team_key = _team_state_key(next_team)
    if next_team_key in game:
        game[next_team_key]["action_points"] = 1


def build_game_state_for_client(room: dict, client_id: str, viewer_team: str):
    """
    クライアント向けのゲーム状態を構築します。
    viewer_team: "team-left" | "team-right" | "spectator" | "questioner"
    """
    game = room.get("game", {})

    if game.get("game_status") != "playing":
        return None

    # 各チームのアクション権情報
    team_left_state = game.get("team_left", {})
    team_right_state = game.get("team_right", {})

    opened_indexes = sorted(list(game.get("opened_char_indexes", set())))
    opened_by_team = game.get("opened_by_team", {})

    return {
        "current_turn_team": game.get("current_turn_team"),
        "game_status": game.get("game_status"),
        "winner": game.get("winner"),
        "is_judging_answer": game.get("pending_answer_judgement") is not None,
        # チームごとの状態
        "team_left": {
            "action_points": team_left_state.get("action_points", 0),
            "bonus_action_points": team_left_state.get("bonus_action_points", 0),
            "correct_answer": team_left_state.get("correct_answer"),
        },
        "team_right": {
            "action_points": team_right_state.get("action_points", 0),
            "bonus_action_points": team_right_state.get("bonus_action_points", 0),
            "correct_answer": team_right_state.get("correct_answer"),
        },
        # オープン状態
        "opened_char_indexes": opened_indexes,
        # viewer_teamでフィルタリング
        "visible_opened_chars": {idx: ("yakumono" if opened_by_team.get(idx) == "yakumono" else viewer_team) if opened_by_team.get(idx) in [viewer_team, "yakumono"] else None for idx in opened_indexes},  # 自分のチームがオープンした場合は自分が見える
    }

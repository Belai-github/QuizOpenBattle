import uuid

from backend.game_logic import (
    _normalized_question_chars,
    apply_end_turn,
    apply_open_character,
    resolve_chat_recipients,
    resolve_client_room_context,
)


async def request_open_vote(manager, client_id: str, char_index):
    ctx = resolve_client_room_context(manager.rooms, client_id)
    if ctx is None:
        await manager.send_private_info(client_id, "ゲーム部屋に参加していません。")
        return

    room = ctx["room"]
    owner_id = ctx["room_owner_id"]

    team = manager._resolve_team_for_client(room, client_id)
    if team is None:
        await manager.send_private_info(client_id, "陣営参加者のみオープンを申請できます。")
        return

    if room.get("game_state") != "playing":
        await manager.send_private_info(client_id, "ゲーム開始後に操作できます。")
        return

    game = room.get("game") or {}
    if game.get("pending_answer_judgement") is not None:
        await manager.send_private_info(client_id, "正誤判定中は行動できません。")
        return

    pending_answer_vote = room.get("pending_answer_vote")
    if pending_answer_vote and pending_answer_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "進行中のアンサー投票があります。")
        return

    pending_turn_end_vote = room.get("pending_turn_end_vote")
    if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "進行中のターンエンド投票があります。")
        return

    pending_intentional_draw_vote = room.get("pending_intentional_draw_vote")
    if pending_intentional_draw_vote and pending_intentional_draw_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "フルオープン決着投票中はオープンを申請できません。")
        return

    if game.get("current_turn_team") != team:
        await manager.send_private_info(client_id, "あなたの陣営のターンではありません。")
        return

    if not isinstance(char_index, int):
        await manager.send_private_info(client_id, "無効な文字インデックスです。")
        return

    question_length = len(_normalized_question_chars(room.get("question_text", "")))
    if char_index < 0 or char_index >= question_length:
        await manager.send_private_info(client_id, "無効な文字インデックスです。")
        return

    pending_vote = room.get("pending_open_vote")
    if pending_vote and pending_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "進行中のオープン投票があります。")
        return

    voter_ids = manager._get_team_participant_ids(room, team)
    if not voter_ids:
        await manager.send_private_info(client_id, "投票対象の陣営参加者がいません。")
        return

    total_voters = len(voter_ids)
    open_log_recipient_ids = {owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))
    team_label = manager._team_label(team)

    if total_voters == 1:
        previous_turn_team = (room.get("game") or {}).get("current_turn_team")
        result = apply_open_character(room, team, char_index)
        vote_id = str(uuid.uuid4())

        if not result.get("ok"):
            await manager.broadcast_state(
                public_info="",
                event_type="open_vote_resolved",
                event_message="",
                event_chat_type=team,
                event_room_id=owner_id,
                event_payload={
                    "vote_id": vote_id,
                    "approved": False,
                    "char_index": char_index,
                    "reason": result.get("error", "open_failed"),
                    "log_marker_id": vote_id,
                },
                event_recipient_ids=open_log_recipient_ids,
            )
            return

        is_yakumono = result.get("is_yakumono", False)
        await manager.broadcast_state(
            public_info="",
            event_type="open_vote_resolved",
            event_message="",
            event_chat_type=team,
            event_room_id=owner_id,
            event_payload={
                "vote_id": vote_id,
                "approved": True,
                "char_index": char_index,
                "is_yakumono": is_yakumono,
                "log_marker_id": vote_id,
            },
            event_recipient_ids=open_log_recipient_ids,
        )

        await manager.broadcast_state(
            public_info=f"{char_index + 1}文字目がオープンされました。",
            event_type="character_opened",
            event_message=manager._format_open_vote_resolution_message(team_label, char_index, True),
            event_chat_type="game-global",
            event_room_id=owner_id,
            event_recipient_ids=open_log_recipient_ids,
            event_payload={
                "team": team,
                "char_index": char_index,
                "is_yakumono": is_yakumono,
            },
        )
        manager._append_kifu_action(
            owner_id,
            "open",
            team,
            client_id,
            {
                "char_index": int(char_index),
                "is_yakumono": bool(is_yakumono),
                "proposed_by_vote": False,
            },
        )

        next_turn_team = (room.get("game") or {}).get("current_turn_team")
        should_notify_turn_changed = (room.get("game") or {}).get("game_status") == "playing" and previous_turn_team != next_turn_team
        if should_notify_turn_changed:
            turn_changed_message = manager._format_turn_changed_message(next_turn_team)
            await manager.broadcast_state(
                public_info=turn_changed_message,
                event_type="turn_changed",
                event_room_id=owner_id,
            )
            await manager._broadcast_team_log_message(owner_id, room, "turn_changed", turn_changed_message)
        return

    vote_id = str(uuid.uuid4())
    required_approvals = (total_voters // 2) + 1
    approved_ids = {client_id} if total_voters > 1 else set()
    room["pending_open_vote"] = {
        "vote_id": vote_id,
        "requester_id": client_id,
        "team": team,
        "char_index": char_index,
        "voter_ids": voter_ids,
        "approved_ids": approved_ids,
        "rejected_ids": set(),
        "required_approvals": required_approvals,
        "status": "pending",
    }

    await manager.broadcast_state(
        public_info="",
        event_type="open_vote_request",
        event_message="",
        event_chat_type=team,
        event_room_id=owner_id,
        event_recipient_ids=open_log_recipient_ids,
        event_payload={
            "vote_id": vote_id,
            "team": team,
            "char_index": char_index,
            "required_approvals": required_approvals,
            "total_voters": total_voters,
            "log_marker_id": vote_id,
        },
    )

    if total_voters > 1:
        await manager.send_private_info(client_id, "提案しました。")


async def respond_open_vote(manager, client_id: str, vote_id: str, approve: bool):
    ctx = resolve_client_room_context(manager.rooms, client_id)
    if ctx is None:
        await manager.send_private_info(client_id, "ゲーム部屋に参加していません。")
        return

    room = ctx["room"]
    owner_id = ctx["room_owner_id"]
    pending_vote = room.get("pending_open_vote")

    if not pending_vote or pending_vote.get("status") != "pending":
        await manager.send_private_info(client_id, "進行中の投票がありません。")
        return

    if pending_vote.get("vote_id") != vote_id:
        await manager.send_private_info(client_id, "投票IDが一致しません。")
        return

    voter_ids = pending_vote["voter_ids"]
    if client_id not in voter_ids:
        await manager.send_private_info(client_id, "この投票には参加できません。")
        return

    if client_id in pending_vote["approved_ids"] or client_id in pending_vote["rejected_ids"]:
        await manager.send_private_info(client_id, "この投票にはすでに回答済みです。")
        return

    if approve:
        pending_vote["approved_ids"].add(client_id)
    else:
        pending_vote["rejected_ids"].add(client_id)

    approvals = len(pending_vote["approved_ids"])
    rejections = len(pending_vote["rejected_ids"])
    required = pending_vote["required_approvals"]
    team = pending_vote["team"]
    char_index = pending_vote["char_index"]
    team_label = manager._team_label(team)
    open_log_recipient_ids = {owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))

    if approvals >= required:
        pending_vote["status"] = "approved"
        previous_turn_team = (room.get("game") or {}).get("current_turn_team")
        result = apply_open_character(room, team, char_index)
        room["pending_open_vote"] = None

        if not result.get("ok"):
            await manager.broadcast_state(
                public_info="",
                event_type="open_vote_resolved",
                event_message="",
                event_chat_type=team,
                event_room_id=owner_id,
                event_payload={
                    "vote_id": vote_id,
                    "approved": False,
                    "char_index": char_index,
                    "reason": result.get("error", "open_failed"),
                    "log_marker_id": vote_id,
                },
                event_recipient_ids=open_log_recipient_ids,
            )
            return

        is_yakumono = result.get("is_yakumono", False)
        await manager.broadcast_state(
            public_info="",
            event_type="open_vote_resolved",
            event_message="",
            event_chat_type=team,
            event_room_id=owner_id,
            event_payload={
                "vote_id": vote_id,
                "approved": True,
                "char_index": char_index,
                "is_yakumono": is_yakumono,
                "log_marker_id": vote_id,
            },
            event_recipient_ids=open_log_recipient_ids,
        )

        await manager.broadcast_state(
            public_info=f"{char_index + 1}文字目がオープンされました。",
            event_type="character_opened",
            event_message=manager._format_open_vote_resolution_message(team_label, char_index, True),
            event_chat_type="game-global",
            event_room_id=owner_id,
            event_recipient_ids=open_log_recipient_ids,
            event_payload={
                "team": team,
                "char_index": char_index,
                "is_yakumono": is_yakumono,
            },
        )
        manager._append_kifu_action(
            owner_id,
            "open",
            team,
            pending_vote.get("requester_id"),
            {
                "char_index": int(char_index),
                "is_yakumono": bool(is_yakumono),
                "proposed_by_vote": True,
                "vote_id": vote_id,
            },
        )

        next_turn_team = (room.get("game") or {}).get("current_turn_team")
        should_notify_turn_changed = (room.get("game") or {}).get("game_status") == "playing" and previous_turn_team != next_turn_team
        if should_notify_turn_changed:
            turn_changed_message = manager._format_turn_changed_message(next_turn_team)
            await manager.broadcast_state(
                public_info=turn_changed_message,
                event_type="turn_changed",
                event_room_id=owner_id,
            )
            await manager._broadcast_team_log_message(owner_id, room, "turn_changed", turn_changed_message)
        return

    max_possible_approvals = approvals + (len(voter_ids) - approvals - rejections)
    if max_possible_approvals < required:
        pending_vote["status"] = "rejected"
        room["pending_open_vote"] = None
        await manager.broadcast_state(
            public_info="",
            event_type="open_vote_resolved",
            event_message="",
            event_chat_type=team,
            event_room_id=owner_id,
            event_payload={
                "vote_id": vote_id,
                "approved": False,
                "char_index": char_index,
                "reason": "rejected",
                "log_marker_id": vote_id,
            },
            event_recipient_ids=open_log_recipient_ids,
        )

        notify_targets = set(pending_vote.get("approved_ids", set()))
        requester_id = pending_vote.get("requester_id")
        if requester_id:
            notify_targets.add(requester_id)
        private_map = {target_id: "オープンの提案が否決されました。" for target_id in notify_targets}
        await manager.broadcast_state(
            public_info="",
            private_map=private_map,
            event_type="private_notice",
            event_room_id=owner_id,
        )


async def respond_answer_vote(manager, client_id: str, vote_id: str, approve: bool):
    ctx = resolve_client_room_context(manager.rooms, client_id)
    if ctx is None:
        await manager.send_private_info(client_id, "ゲーム部屋に参加していません。")
        return

    room = ctx["room"]
    owner_id = ctx["room_owner_id"]
    pending_vote = room.get("pending_answer_vote")

    if not pending_vote or pending_vote.get("status") != "pending":
        await manager.send_private_info(client_id, "進行中のアンサー投票がありません。")
        return

    if pending_vote.get("vote_id") != vote_id:
        await manager.send_private_info(client_id, "投票IDが一致しません。")
        return

    voter_ids = pending_vote["voter_ids"]
    if client_id not in voter_ids:
        await manager.send_private_info(client_id, "この投票には参加できません。")
        return

    if client_id in pending_vote["approved_ids"] or client_id in pending_vote["rejected_ids"]:
        await manager.send_private_info(client_id, "この投票にはすでに回答済みです。")
        return

    if approve:
        pending_vote["approved_ids"].add(client_id)
    else:
        pending_vote["rejected_ids"].add(client_id)

    approvals = len(pending_vote["approved_ids"])
    rejections = len(pending_vote["rejected_ids"])
    required = pending_vote["required_approvals"]
    team = pending_vote["team"]
    team_label = manager._team_label(team)
    answer_text = str(pending_vote.get("answer_text", "")).strip()
    requester_id = pending_vote.get("requester_id")
    requester_name = manager.nicknames.get(requester_id, "ゲスト")

    team_chat_recipients = set(voter_ids)
    team_chat_result = resolve_chat_recipients(owner_id, room, team, team)
    if team_chat_result.get("ok"):
        team_chat_recipients = team_chat_result["event_recipient_ids"]

    if approvals >= required:
        pending_vote["status"] = "approved"
        room["pending_answer_vote"] = None

        game = room.get("game") or {}
        if game.get("pending_answer_judgement") is not None:
            await manager.broadcast_state(
                public_info="",
                event_type="answer_vote_resolved",
                event_message="",
                event_chat_type=team,
                event_room_id=owner_id,
                event_recipient_ids=team_chat_recipients,
                event_payload={
                    "vote_id": vote_id,
                    "approved": False,
                    "team": team,
                    "reason": "judgement_pending",
                    "log_marker_id": vote_id,
                },
            )
            return

        answer_log_marker_id = str(uuid.uuid4())
        game["pending_answer_judgement"] = {
            "team": team,
            "answer_text": answer_text,
            "answerer_id": requester_id,
            "answer_log_marker_id": answer_log_marker_id,
        }
        manager._append_kifu_action(
            owner_id,
            "answer",
            team,
            requester_id,
            {
                "answer_text": answer_text,
                "proposed_by_vote": True,
                "vote_id": vote_id,
            },
        )

        if not room.get("is_ai_mode"):
            await manager.broadcast_state(
                public_info=f"{team_label}が解答を提出しました。出題者が正誤判定中です。",
                event_type="answer_attempt",
                event_room_id=owner_id,
                event_payload={
                    "team": team,
                    "log_marker_id": answer_log_marker_id,
                },
            )
        await manager._broadcast_team_log_message(
            owner_id,
            room,
            "answer_attempt",
            manager._format_answer_attempt_message(team_label, answer_text),
            event_payload={
                "team": team,
                "log_marker_id": answer_log_marker_id,
            },
        )

        await manager.broadcast_state(
            public_info="",
            event_type="answer_vote_resolved",
            event_message="",
            event_chat_type=team,
            event_room_id=owner_id,
            event_recipient_ids=team_chat_recipients,
            event_payload={
                "vote_id": vote_id,
                "approved": True,
                "team": team,
                "log_marker_id": vote_id,
            },
        )

        if room.get("is_ai_mode"):
            await manager._resolve_ai_answer_judgement(owner_id, room, team, answer_text)
            return

        await manager.broadcast_state(
            public_info="",
            event_type="answer_judgement_request",
            event_room_id=owner_id,
            event_recipient_ids={owner_id},
            event_payload={
                "team": team,
                "team_label": team_label,
                "answer_text": answer_text,
                "answerer_name": requester_name,
            },
        )
        return

    max_possible_approvals = approvals + (len(voter_ids) - approvals - rejections)
    if max_possible_approvals < required:
        pending_vote["status"] = "rejected"
        room["pending_answer_vote"] = None
        await manager.broadcast_state(
            public_info="",
            event_type="answer_vote_resolved",
            event_message="",
            event_chat_type=team,
            event_room_id=owner_id,
            event_recipient_ids=team_chat_recipients,
            event_payload={
                "vote_id": vote_id,
                "approved": False,
                "team": team,
                "reason": "rejected",
                "log_marker_id": vote_id,
            },
        )

        notify_targets = set(pending_vote.get("approved_ids", set()))
        requester_id = pending_vote.get("requester_id")
        if requester_id:
            notify_targets.add(requester_id)
        private_map = {target_id: "アンサーの提案が否決されました。" for target_id in notify_targets}
        await manager.broadcast_state(
            public_info="",
            private_map=private_map,
            event_type="private_notice",
            event_room_id=owner_id,
        )
        return


async def request_turn_end_attempt(manager, client_id: str):
    ctx = resolve_client_room_context(manager.rooms, client_id)
    if ctx is None:
        await manager.send_private_info(client_id, "ゲーム部屋に参加していません。")
        return

    room = ctx["room"]
    owner_id = ctx["room_owner_id"]
    if room.get("game_state") != "playing":
        await manager.send_private_info(client_id, "対戦中のみターンエンドできます。")
        return

    game = room.get("game") or {}
    if game.get("pending_answer_judgement") is not None:
        await manager.send_private_info(client_id, "正誤判定中は行動できません。")
        return

    full_open = manager._get_full_open_settlement_state(room)
    if isinstance(full_open, dict) and str(full_open.get("state") or "idle") != "idle":
        await manager.send_private_info(client_id, "フルオープン決着中はターンエンドできません。")
        return

    pending_open_vote = room.get("pending_open_vote")
    if pending_open_vote and pending_open_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "文字オープン投票中はターンエンドできません。")
        return

    pending_answer_vote = room.get("pending_answer_vote")
    if pending_answer_vote and pending_answer_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "アンサー投票中はターンエンドできません。")
        return

    pending_turn_end_vote = room.get("pending_turn_end_vote")
    if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "進行中のターンエンド投票があります。")
        return

    pending_intentional_draw_vote = room.get("pending_intentional_draw_vote")
    if pending_intentional_draw_vote and pending_intentional_draw_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "フルオープン決着投票中はターンエンドできません。")
        return

    team = manager._resolve_team_for_client(room, client_id)
    if team is None:
        await manager.send_private_info(client_id, "参加者のみターンエンドできます。")
        return

    if game.get("current_turn_team") != team:
        await manager.send_private_info(client_id, "自分のターンでのみターンエンドできます。")
        return

    voter_ids = manager._get_team_participant_ids(room, team)
    if not voter_ids:
        await manager.send_private_info(client_id, "投票対象の陣営参加者がいません。")
        return

    total_voters = len(voter_ids)
    if total_voters == 1:
        result = apply_end_turn(room, team)
        if not result.get("ok"):
            await manager.send_private_info(client_id, result.get("error", "ターン終了に失敗しました。"))
            return

        manager._append_kifu_action(
            owner_id,
            "turn_end",
            team,
            client_id,
            {
                "next_turn_team": str(result.get("current_turn_team") or ""),
                "proposed_by_vote": False,
            },
        )

        game_after = room.get("game") or {}
        if game_after.get("game_status") == "finished":
            winner = game_after.get("winner")
            game_finished_message = manager._format_game_finished_message(winner)
            await manager._broadcast_game_finished_message(owner_id, room, game_finished_message)
            manager._finalize_kifu_if_tracking(owner_id, room, "finished")
        else:
            next_team = result.get("current_turn_team")
            turn_changed_message = manager._format_turn_changed_message(next_team)
            await manager.broadcast_state(
                public_info=turn_changed_message,
                event_type="turn_changed",
                event_room_id=owner_id,
            )
            await manager._broadcast_team_log_message(owner_id, room, "turn_changed", turn_changed_message)
        await manager.send_private_info(client_id, "ターンエンドしました。")
        return

    vote_id = str(uuid.uuid4())
    required_approvals = (total_voters // 2) + 1
    room["pending_turn_end_vote"] = {
        "vote_id": vote_id,
        "requester_id": client_id,
        "team": team,
        "voter_ids": voter_ids,
        "approved_ids": {client_id},
        "rejected_ids": set(),
        "required_approvals": required_approvals,
        "status": "pending",
    }

    team_label = manager._team_label(team)
    await manager.broadcast_state(
        public_info="",
        event_type="turn_end_vote_request",
        event_message="",
        event_chat_type=team,
        event_room_id=owner_id,
        event_recipient_ids=voter_ids - {client_id},
        event_payload={
            "vote_id": vote_id,
            "team": team,
            "team_label": team_label,
            "required_approvals": required_approvals,
            "total_voters": total_voters,
            "log_marker_id": vote_id,
        },
    )

    await manager.send_private_info(client_id, "提案しました。")


async def request_intentional_draw_vote(manager, client_id: str):
    ctx = resolve_client_room_context(manager.rooms, client_id)
    if ctx is None:
        await manager.send_private_info(client_id, "ゲーム部屋に参加していません。")
        return

    room = ctx["room"]
    owner_id = ctx["room_owner_id"]

    if room.get("game_state") != "playing":
        await manager.send_private_info(client_id, "対戦中のみフルオープン決着を提案できます。")
        return

    game = room.get("game") or {}
    if game.get("pending_answer_judgement") is not None:
        await manager.send_private_info(client_id, "正誤判定中はフルオープン決着を提案できません。")
        return

    pending_open_vote = room.get("pending_open_vote")
    if pending_open_vote and pending_open_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "文字オープン投票中はフルオープン決着を提案できません。")
        return

    pending_answer_vote = room.get("pending_answer_vote")
    if pending_answer_vote and pending_answer_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "アンサー投票中はフルオープン決着を提案できません。")
        return

    pending_turn_end_vote = room.get("pending_turn_end_vote")
    if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "ターンエンド投票中はフルオープン決着を提案できません。")
        return

    pending_intentional_draw_vote = room.get("pending_intentional_draw_vote")
    if pending_intentional_draw_vote and pending_intentional_draw_vote.get("status") == "pending":
        await manager.send_private_info(client_id, "進行中のフルオープン決着投票があります。")
        return

    if not manager._is_intentional_draw_eligible(room):
        await manager.send_private_info(client_id, "フルオープン決着を提案できる条件を満たしていません。")
        return

    voter_ids = set(room.get("left_participants", set())) | set(room.get("right_participants", set()))
    if not voter_ids:
        await manager.send_private_info(client_id, "投票対象の参加者がいません。")
        return

    vote_id = str(uuid.uuid4())
    required_approvals = len(voter_ids)
    requester_name = manager.nicknames.get(client_id, "ゲスト")
    room["pending_intentional_draw_vote"] = {
        "vote_id": vote_id,
        "requester_id": client_id,
        "voter_ids": voter_ids,
        "approved_ids": ({client_id} if client_id in voter_ids else set()),
        "rejected_ids": set(),
        "required_approvals": required_approvals,
        "status": "pending",
    }

    await manager.broadcast_state(
        public_info="",
        event_type="intentional_draw_vote_request",
        event_message="",
        event_chat_type="game-global",
        event_room_id=owner_id,
        event_recipient_ids=voter_ids - {client_id},
        event_payload={
            "vote_id": vote_id,
            "required_approvals": required_approvals,
            "total_voters": len(voter_ids),
            "requester_name": requester_name,
            "log_marker_id": vote_id,
        },
    )

    await manager.send_private_info(client_id, "フルオープン決着を提案しました。")


async def respond_intentional_draw_vote(manager, client_id: str, vote_id: str, approve: bool):
    ctx = resolve_client_room_context(manager.rooms, client_id)
    if ctx is None:
        await manager.send_private_info(client_id, "ゲーム部屋に参加していません。")
        return

    room = ctx["room"]
    owner_id = ctx["room_owner_id"]
    pending_vote = room.get("pending_intentional_draw_vote")

    if not pending_vote or pending_vote.get("status") != "pending":
        await manager.send_private_info(client_id, "進行中のフルオープン決着投票がありません。")
        return

    if pending_vote.get("vote_id") != vote_id:
        await manager.send_private_info(client_id, "投票IDが一致しません。")
        return

    voter_ids = set(pending_vote.get("voter_ids", set()))
    if client_id not in voter_ids:
        await manager.send_private_info(client_id, "この投票には参加できません。")
        return

    approved_ids = set(pending_vote.get("approved_ids", set()))
    rejected_ids = set(pending_vote.get("rejected_ids", set()))
    if client_id in approved_ids or client_id in rejected_ids:
        await manager.send_private_info(client_id, "この投票にはすでに回答済みです。")
        return

    if approve:
        approved_ids.add(client_id)
    else:
        rejected_ids.add(client_id)

    pending_vote["approved_ids"] = approved_ids
    pending_vote["rejected_ids"] = rejected_ids

    approvals = len(approved_ids)
    required = int(pending_vote.get("required_approvals") or 0)
    recipients = {owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))

    if approvals >= required:
        pending_vote["status"] = "approved"
        room["pending_intentional_draw_vote"] = None

        manager._start_full_open_settlement(room, vote_id, str(pending_vote.get("requester_id") or ""))
        manager._append_kifu_action(
            owner_id,
            "intentional_draw",
            "game-global",
            pending_vote.get("requester_id"),
            {
                "proposed_by_vote": True,
                "vote_id": vote_id,
            },
        )
        room["pending_open_vote"] = None
        room["pending_answer_vote"] = None
        room["pending_turn_end_vote"] = None

        await manager.broadcast_state(
            public_info="",
            event_type="intentional_draw_vote_resolved",
            event_message="",
            event_chat_type="game-global",
            event_room_id=owner_id,
            event_recipient_ids=recipients,
            event_payload={
                "vote_id": vote_id,
                "approved": True,
                "log_marker_id": vote_id,
            },
        )

        await manager.broadcast_state(
            public_info="フルオープン決着が成立しました。回答待機を開始します。",
            event_type="full_open_settlement_start",
            event_message="フルオープン決着が成立しました。回答待機を開始します。",
            event_chat_type="game-global",
            event_room_id=owner_id,
            event_recipient_ids=recipients,
            event_payload={
                "vote_id": vote_id,
                "log_marker_id": vote_id,
            },
        )

        await manager.broadcast_state(
            public_info="フルオープン決着が成立しました。問題文の全文を開示して、両陣営の回答を待機します。",
            event_type="intentional_draw",
            event_message="フルオープン決着が成立しました。全文を開示して回答待機に移行します。",
            event_chat_type="game-global",
            event_room_id=owner_id,
            event_recipient_ids=recipients,
            event_payload={
                "vote_id": vote_id,
                "log_marker_id": vote_id,
            },
        )
        return

    if len(rejected_ids) > 0:
        pending_vote["status"] = "rejected"
        room["pending_intentional_draw_vote"] = None
        await manager.broadcast_state(
            public_info="",
            event_type="intentional_draw_vote_resolved",
            event_message="",
            event_chat_type="game-global",
            event_room_id=owner_id,
            event_recipient_ids=recipients,
            event_payload={
                "vote_id": vote_id,
                "approved": False,
                "reason": "rejected",
                "log_marker_id": vote_id,
            },
        )

        requester_id = pending_vote.get("requester_id")
        notify_targets = set(approved_ids)
        if requester_id:
            notify_targets.add(str(requester_id))
        private_map = {target_id: "フルオープン決着の提案が否決されました。" for target_id in notify_targets}
        await manager.broadcast_state(
            public_info="",
            private_map=private_map,
            event_type="private_notice",
            event_room_id=owner_id,
        )
        return


async def respond_turn_end_vote(manager, client_id: str, vote_id: str, approve: bool):
    ctx = resolve_client_room_context(manager.rooms, client_id)
    if ctx is None:
        await manager.send_private_info(client_id, "ゲーム部屋に参加していません。")
        return

    room = ctx["room"]
    owner_id = ctx["room_owner_id"]
    pending_vote = room.get("pending_turn_end_vote")

    if not pending_vote or pending_vote.get("status") != "pending":
        await manager.send_private_info(client_id, "進行中のターンエンド投票がありません。")
        return

    if pending_vote.get("vote_id") != vote_id:
        await manager.send_private_info(client_id, "投票IDが一致しません。")
        return

    voter_ids = pending_vote["voter_ids"]
    if client_id not in voter_ids:
        await manager.send_private_info(client_id, "この投票には参加できません。")
        return

    if client_id in pending_vote["approved_ids"] or client_id in pending_vote["rejected_ids"]:
        await manager.send_private_info(client_id, "この投票にはすでに回答済みです。")
        return

    if approve:
        pending_vote["approved_ids"].add(client_id)
    else:
        pending_vote["rejected_ids"].add(client_id)

    approvals = len(pending_vote["approved_ids"])
    rejections = len(pending_vote["rejected_ids"])
    required = pending_vote["required_approvals"]
    team = pending_vote["team"]

    team_chat_recipients = set(voter_ids)
    team_chat_result = resolve_chat_recipients(owner_id, room, team, team)
    if team_chat_result.get("ok"):
        team_chat_recipients = team_chat_result["event_recipient_ids"]

    if approvals >= required:
        pending_vote["status"] = "approved"
        room["pending_turn_end_vote"] = None

        result = apply_end_turn(room, team)
        if not result.get("ok"):
            await manager.broadcast_state(
                public_info="",
                event_type="turn_end_vote_resolved",
                event_message="",
                event_chat_type=team,
                event_room_id=owner_id,
                event_recipient_ids=team_chat_recipients,
                event_payload={
                    "vote_id": vote_id,
                    "approved": False,
                    "reason": result.get("error", "end_turn_failed"),
                    "log_marker_id": vote_id,
                },
            )
            return

        manager._append_kifu_action(
            owner_id,
            "turn_end",
            team,
            pending_vote.get("requester_id"),
            {
                "next_turn_team": str(result.get("current_turn_team") or ""),
                "proposed_by_vote": True,
                "vote_id": vote_id,
            },
        )

        await manager.broadcast_state(
            public_info="",
            event_type="turn_end_vote_resolved",
            event_message="",
            event_chat_type=team,
            event_room_id=owner_id,
            event_recipient_ids=team_chat_recipients,
            event_payload={
                "vote_id": vote_id,
                "approved": True,
                "log_marker_id": vote_id,
            },
        )

        game_after = room.get("game") or {}
        if game_after.get("game_status") == "finished":
            winner = game_after.get("winner")
            game_finished_message = manager._format_game_finished_message(winner)
            await manager._broadcast_game_finished_message(owner_id, room, game_finished_message)
            manager._finalize_kifu_if_tracking(owner_id, room, "finished")
        else:
            next_team = result.get("current_turn_team")
            turn_changed_message = manager._format_turn_changed_message(next_team)
            await manager.broadcast_state(
                public_info=turn_changed_message,
                event_type="turn_changed",
                event_room_id=owner_id,
            )
            await manager._broadcast_team_log_message(owner_id, room, "turn_changed", turn_changed_message)
        return

    max_possible_approvals = approvals + (len(voter_ids) - approvals - rejections)
    if max_possible_approvals < required:
        pending_vote["status"] = "rejected"
        room["pending_turn_end_vote"] = None
        await manager.broadcast_state(
            public_info="",
            event_type="turn_end_vote_resolved",
            event_message="",
            event_chat_type=team,
            event_room_id=owner_id,
            event_recipient_ids=team_chat_recipients,
            event_payload={
                "vote_id": vote_id,
                "approved": False,
                "reason": "rejected",
                "log_marker_id": vote_id,
            },
        )
        return

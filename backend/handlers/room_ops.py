from backend.game_logic import (
    apply_join_room,
    apply_shuffle_participants,
    apply_swap_participant_team,
    remove_client_from_all_rooms as remove_client_from_all_rooms_logic,
    resolve_client_room_context,
)


async def cancel_question(manager, requester_id: str, room_owner_id: str):
    room = manager.rooms.get(room_owner_id)
    if room is None:
        await manager.send_private_info(requester_id, "取り消し対象の部屋が見つかりません。")
        return

    if requester_id != room_owner_id:
        await manager.send_private_info(requester_id, "出題取消は出題者のみ実行できます。")
        return

    questioner_name = room["questioner_name"]
    affected_client_ids = set(room["left_participants"]) | set(room["right_participants"]) | set(room["spectators"])
    affected_client_ids.discard(requester_id)
    manager.rooms.pop(room_owner_id, None)
    manager._finalize_kifu_if_tracking(room_owner_id, room, "owner_cancelled")
    manager._clear_room_reconnect_reservations(room_owner_id)

    await manager.send_private_info(
        requester_id,
        "部屋を閉じました。",
        target_screen="waiting_room",
        event_type="room_closed",
    )

    for target_client_id in affected_client_ids:
        await manager.send_private_info(
            target_client_id,
            "出題が取り消されたため、部屋から退室しました。",
            target_screen="waiting_room",
            event_type="forced_exit_notice",
        )

    await manager.broadcast_state(
        public_info=f"{questioner_name} の出題が取り消されました",
        event_type="room_closed",
        event_message=f"{questioner_name} が出題を取り消しました",
        event_room_id=room_owner_id,
    )


def remove_client_from_all_rooms(manager, client_id: str):
    remove_client_from_all_rooms_logic(manager.rooms, client_id)


async def join_room(manager, client_id: str, room_owner_id: str, role: str):
    manager._cancel_disconnect_grace_timer(client_id)
    manager._clear_pending_disconnect_everywhere(client_id)
    manager.reconnect_reservations.pop(client_id, None)
    result = apply_join_room(manager.rooms, client_id, room_owner_id, role)
    if not result.get("ok"):
        await manager.send_private_info(client_id, result.get("error", "部屋への入室に失敗しました。"))
        return

    await manager.send_private_info(
        client_id,
        result.get("entry_message", "部屋に入りました。"),
        target_screen=result.get("target_screen"),
    )

    joined_ctx = resolve_client_room_context(manager.rooms, client_id)
    if result.get("target_screen") == "game_arena" and joined_ctx is not None and joined_ctx.get("role") == "participant" and joined_ctx.get("room_owner_id") == room_owner_id:
        await manager._resend_pending_votes_to_client(room_owner_id, client_id)

    role_name = result.get("event_role_name")
    if role_name is None:
        return

    room = manager.rooms.get(room_owner_id)
    if room is None:
        return

    joined_ctx = resolve_client_room_context(manager.rooms, client_id)
    if joined_ctx is not None and joined_ctx.get("room_owner_id") == room_owner_id and joined_ctx.get("role") == "spectator" and room.get("game_state") in {"playing", "finished"}:
        manager._touch_kifu_spectator_if_tracking(room_owner_id, client_id)

    nickname = manager.nicknames.get(client_id, "ゲスト")
    await manager.broadcast_state(
        public_info=f"{nickname} が部屋に入りました",
        event_type="room_entry",
        event_message=f"{nickname} が {room['questioner_name']} の部屋に{role_name}として参加しました",
        event_room_id=room_owner_id,
    )


async def shuffle_participants(manager, client_id: str):
    result = apply_shuffle_participants(manager.rooms, client_id)
    if not result.get("ok"):
        await manager.send_private_info(client_id, result.get("error", "参加者シャッフルに失敗しました。"))
        return

    room = manager.rooms.get(client_id)
    is_ai_mode = bool(room and room.get("is_ai_mode"))
    actor_name = manager.nicknames.get(client_id, "ゲスト") if is_ai_mode else result["questioner_name"]
    await manager.broadcast_state(
        public_info=f"{actor_name} が参加者をシャッフルしました",
        event_type="room_shuffle",
        event_message=f"{actor_name} が参加者をシャッフルしました",
        event_room_id=client_id,
    )


async def swap_participant_team(manager, client_id: str, target_client_id: str):
    result = apply_swap_participant_team(manager.rooms, client_id, target_client_id)
    if not result.get("ok"):
        await manager.send_private_info(client_id, result.get("error", "参加者入れ替えに失敗しました。"))
        return

    room = manager.rooms.get(client_id)
    is_ai_mode = bool(room and room.get("is_ai_mode"))
    actor_name = manager.nicknames.get(client_id, "ゲスト") if is_ai_mode else result["questioner_name"]
    target_id = str(result.get("target_client_id") or "").strip()
    from_team = str(result.get("from_team") or "")
    to_team = str(result.get("to_team") or "")
    target_name = manager.nicknames.get(target_id, "ゲスト")
    from_label = manager._team_label(from_team)
    to_label = manager._team_label(to_team)

    await manager.broadcast_state(
        public_info=f"{actor_name} が参加者を入れ替えました",
        event_type="room_shuffle",
        event_message=f"{actor_name} が {target_name} を {from_label}から{to_label} に入れ替えました",
        event_room_id=client_id,
    )

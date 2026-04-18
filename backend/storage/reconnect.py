import asyncio
import time


def set_room_pending_disconnect(manager, room_owner_id: str, client_id: str, nickname: str, team: str, expires_at: float):
    room = manager.rooms.get(room_owner_id)
    if room is None:
        return

    pending_disconnects = room.setdefault("pending_disconnects", {})
    if not isinstance(pending_disconnects, dict):
        pending_disconnects = {}
        room["pending_disconnects"] = pending_disconnects

    pending_disconnects[client_id] = {
        "nickname": nickname,
        "team": team,
        "expires_at": expires_at,
    }


def clear_room_pending_disconnect(manager, room_owner_id: str, client_id: str):
    room = manager.rooms.get(room_owner_id)
    if room is None:
        return

    pending_disconnects = room.get("pending_disconnects")
    if not isinstance(pending_disconnects, dict):
        return

    pending_disconnects.pop(client_id, None)
    if not pending_disconnects:
        room["pending_disconnects"] = {}


def clear_pending_disconnect_everywhere(manager, client_id: str):
    for room in manager.rooms.values():
        pending_disconnects = room.get("pending_disconnects")
        if not isinstance(pending_disconnects, dict):
            continue

        pending_disconnects.pop(client_id, None)
        if not pending_disconnects:
            room["pending_disconnects"] = {}


def purge_expired_reconnect_reservations(manager):
    now = time.time()
    for client_id, reservation in list(manager.reconnect_reservations.items()):
        if str(reservation.get("kind") or "participant") != "participant":
            continue

        expires_at = reservation.get("expires_at")
        if not isinstance(expires_at, (int, float)):
            continue

        if expires_at > now:
            continue

        room_owner_id = reservation.get("room_owner_id")
        manager.reconnect_reservations.pop(client_id, None)
        manager._cancel_disconnect_grace_timer(client_id)
        if room_owner_id:
            clear_room_pending_disconnect(manager, str(room_owner_id), client_id)


def clear_room_reconnect_reservations(manager, room_owner_id: str):
    for client_id, reservation in list(manager.reconnect_reservations.items()):
        if reservation.get("room_owner_id") != room_owner_id:
            continue

        manager.reconnect_reservations.pop(client_id, None)
        manager._cancel_disconnect_grace_timer(client_id)

    room = manager.rooms.get(room_owner_id)
    if room is not None:
        pending_disconnects = room.get("pending_disconnects")
        if isinstance(pending_disconnects, dict):
            pending_disconnects.clear()
            room["pending_disconnects"] = {}


def reserve_participant_reconnect(manager, client_id: str, ctx: dict | None):
    nickname = manager.nicknames.get(client_id, "ゲスト")

    if ctx and ctx.get("role") == "participant":
        room = ctx.get("room") or {}
        if room.get("game_state") != "playing":
            return None

        team = ctx.get("chat_role")
        if team not in {"team-left", "team-right"}:
            return None

        expires_at = time.time() + manager.DISCONNECT_GRACE_SECONDS
        reservation = {
            "kind": "participant",
            "room_owner_id": ctx.get("room_owner_id"),
            "team": team,
            "expires_at": expires_at,
            "nickname": nickname,
            "user_id": str(manager.client_user_ids.get(client_id) or "").strip(),
        }
        manager.reconnect_reservations[client_id] = reservation
        return reservation

    if ctx and ctx.get("role") == "owner":
        room = ctx.get("room") or {}
        if room.get("game_state") == "playing":
            reservation = {
                "kind": "owner",
                "room_owner_id": ctx.get("room_owner_id"),
                "team": "questioner",
                "expires_at": None,
                "nickname": nickname,
            }
            manager.reconnect_reservations[client_id] = reservation
            return reservation
        return None

    owned_room = manager.rooms.get(client_id)
    if not isinstance(owned_room, dict):
        return None

    if not bool(owned_room.get("is_ai_mode")):
        return None

    if owned_room.get("game_state") != "playing":
        return None

    if manager._is_owner_joined_as_guest(client_id, owned_room):
        return None

    reservation = {
        "kind": "owner",
        "room_owner_id": client_id,
        "team": "questioner",
        "expires_at": None,
        "nickname": nickname,
    }
    manager.reconnect_reservations[client_id] = reservation
    return reservation


def try_restore_participant_reconnect(manager, client_id: str):
    manager._purge_expired_reconnect_reservations()

    reservation = manager.reconnect_reservations.get(client_id)
    if not reservation:
        return None

    kind = str(reservation.get("kind") or "participant")
    room_owner_id = reservation.get("room_owner_id")
    room = manager.rooms.get(room_owner_id)
    if room is None:
        manager.reconnect_reservations.pop(client_id, None)
        return None

    if kind == "owner":
        manager.reconnect_reservations.pop(client_id, None)
        manager._cancel_disconnect_grace_timer(client_id)
        return {
            "room_owner_id": room_owner_id,
            "kind": "owner",
        }

    team = reservation.get("team")
    room["left_participants"].discard(client_id)
    room["right_participants"].discard(client_id)
    room["spectators"].discard(client_id)

    if team == "team-left":
        room["left_participants"].add(client_id)
    elif team == "team-right":
        room["right_participants"].add(client_id)
    else:
        manager.reconnect_reservations.pop(client_id, None)
        return None

    manager.reconnect_reservations.pop(client_id, None)
    clear_room_pending_disconnect(manager, room_owner_id, client_id)
    manager._cancel_disconnect_grace_timer(client_id)
    return {
        "room_owner_id": room_owner_id,
        "kind": "participant",
    }


async def finalize_participant_disconnect_after_grace(
    manager,
    client_id: str,
    room_owner_id: str,
    expires_at: float,
    nickname: str,
):
    wait_seconds = max(0.0, expires_at - time.time())
    try:
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        if client_id in manager.active_connections:
            return

        reservation = manager.reconnect_reservations.get(client_id)
        if not reservation:
            return

        if str(reservation.get("kind") or "participant") != "participant":
            return

        if reservation.get("room_owner_id") != room_owner_id:
            return

        room = manager.rooms.get(room_owner_id)
        if room is None:
            manager.reconnect_reservations.pop(client_id, None)
            return

        manager.reconnect_reservations.pop(client_id, None)
        clear_room_pending_disconnect(manager, room_owner_id, client_id)
        manager._mark_forced_loss_user_id(
            room,
            reservation.get("user_id"),
            reservation.get("team"),
        )

        room["left_participants"].discard(client_id)
        room["right_participants"].discard(client_id)
        room["spectators"].discard(client_id)

        await manager.broadcast_state(
            public_info=f"{nickname} の再接続猶予が切れ、部屋から退室しました。",
            event_type="participant_timeout_expired",
            event_message=f"{nickname} の接続タイムアウト猶予が終了しました。",
            event_room_id=room_owner_id,
        )

        await manager._evaluate_team_forfeit_if_needed(room_owner_id, room)

    except asyncio.CancelledError:
        pass
    finally:
        active_task = manager.pending_disconnect_tasks.get(client_id)
        if active_task is asyncio.current_task():
            manager.pending_disconnect_tasks.pop(client_id, None)


def schedule_participant_disconnect_grace(
    manager,
    client_id: str,
    room_owner_id: str,
    expires_at: float,
    nickname: str,
):
    manager._cancel_disconnect_grace_timer(client_id)
    task = asyncio.create_task(
        finalize_participant_disconnect_after_grace(
            manager,
            client_id,
            room_owner_id,
            expires_at,
            nickname,
        )
    )
    manager.pending_disconnect_tasks[client_id] = task

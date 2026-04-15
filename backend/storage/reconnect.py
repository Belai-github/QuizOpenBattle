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

import asyncio
import unittest
from unittest.mock import patch

from backend.auth import (
    WebSocketAuthManager,
    is_valid_client_id,
    sanitize_nickname,
)
from backend.broadcast import (
    resolve_arena_history_chat_type,
    resolve_event_timestamp,
    resolve_log_marker_id,
)
from backend.events.identity import derive_event_identity
from backend.storage.reconnect import (
    clear_room_pending_disconnect,
    reserve_participant_reconnect,
    set_room_pending_disconnect,
    try_restore_participant_reconnect,
)


class TestAuthContracts(unittest.TestCase):
    def test_sanitize_nickname_defaults_and_truncates(self):
        self.assertEqual(sanitize_nickname(None), "ゲスト")
        self.assertEqual(sanitize_nickname("   "), "ゲスト")
        self.assertEqual(sanitize_nickname("x" * 40), "x" * 24)

    def test_client_id_validation(self):
        self.assertTrue(is_valid_client_id("Abc_12345-xyz"))
        self.assertFalse(is_valid_client_id("short"))
        self.assertFalse(is_valid_client_id("contains space"))

    def test_ws_ticket_issue_and_verify_success_and_reuse(self):
        manager = WebSocketAuthManager()
        manager.ticket_ttl_seconds = 30

        ticket_payload = manager.issue_ticket("Client_12345", "Alice")
        ticket = ticket_payload["ticket"]

        ok, reason = manager.verify_ticket(ticket, "Client_12345", "Alice")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

        ok2, reason2 = manager.verify_ticket(ticket, "Client_12345", "Alice")
        self.assertFalse(ok2)
        self.assertEqual(reason2, "reused_ticket")


class TestEventIdentityContracts(unittest.TestCase):
    def test_derive_event_identity_prefers_payload_event_id_and_scope_default(self):
        rooms = {"roomA": {"arena_event_id_seq": 3}}

        identity = derive_event_identity(
            event_room_id="roomA",
            event_type="answer_vote_resolved",
            event_chat_type="",
            event_payload={"event_id": "evt-custom", "vote_id": "v1"},
            rooms=rooms,
            next_room_event_id=lambda rid: f"{rid}:next",
        )

        self.assertEqual(identity["event_id"], "evt-custom")
        self.assertEqual(identity["event_scope"], "game-global")
        self.assertEqual(identity["event_revision"], 2)
        self.assertEqual(identity["event_version"], 4)

    def test_derive_event_identity_uses_vote_marker_and_revision(self):
        rooms = {}

        identity = derive_event_identity(
            event_room_id=None,
            event_type="open_vote_request",
            event_chat_type="team-left",
            event_payload={"vote_id": "vote-1"},
            rooms=rooms,
            next_room_event_id=lambda rid: f"{rid}:next",
        )

        self.assertEqual(identity["event_id"], "vote:vote-1")
        self.assertEqual(identity["event_scope"], "team-left")
        self.assertEqual(identity["event_revision"], 1)


class TestBroadcastContracts(unittest.TestCase):
    def test_resolve_event_timestamp_prefers_payload_and_falls_back_to_now(self):
        self.assertEqual(resolve_event_timestamp({"event_timestamp": 1234}), 1234)
        self.assertEqual(resolve_event_timestamp({"event_timestamp": "5678"}), 5678)

        with patch("backend.broadcast.time.time", return_value=1.234):
            self.assertEqual(resolve_event_timestamp({}), 1234)

    def test_resolve_log_marker_id_and_chat_type_mapping(self):
        self.assertEqual(resolve_log_marker_id({"log_marker_id": "m-1"}), "m-1")
        self.assertEqual(resolve_log_marker_id({"vote_id": "v-2"}), "v-2")
        self.assertIsNone(resolve_log_marker_id({}))

        self.assertEqual(resolve_arena_history_chat_type("room_entry", None), "game-global")
        self.assertEqual(resolve_arena_history_chat_type("question", None), "game-global")
        self.assertEqual(resolve_arena_history_chat_type("chat", "team-right"), "team-right")
        self.assertIsNone(resolve_arena_history_chat_type("chat", None))


class DummyReconnectManager:
    DISCONNECT_GRACE_SECONDS = 5

    def __init__(self):
        self.rooms = {
            "owner1": {
                "game_state": "playing",
                "left_participants": set(),
                "right_participants": set(),
                "spectators": set(),
                "pending_disconnects": {},
                "is_ai_mode": False,
            }
        }
        self.nicknames = {"c1": "Alice", "owner1": "Owner"}
        self.reconnect_reservations = {}
        self.pending_disconnect_tasks = {}

    def _is_owner_joined_as_guest(self, owner_id, room):
        return False

    def _cancel_disconnect_grace_timer(self, client_id):
        self.pending_disconnect_tasks.pop(client_id, None)

    def _purge_expired_reconnect_reservations(self):
        pass


class TestReconnectContracts(unittest.TestCase):
    def test_reserve_participant_reconnect_and_restore(self):
        manager = DummyReconnectManager()
        ctx = {
            "role": "participant",
            "room_owner_id": "owner1",
            "room": manager.rooms["owner1"],
            "chat_role": "team-left",
        }

        reservation = reserve_participant_reconnect(manager, "c1", ctx)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation["kind"], "participant")

        set_room_pending_disconnect(manager, "owner1", "c1", "Alice", "team-left", 9999999999)
        restored = try_restore_participant_reconnect(manager, "c1")

        self.assertEqual(restored, {"room_owner_id": "owner1", "kind": "participant"})
        self.assertIn("c1", manager.rooms["owner1"]["left_participants"])
        self.assertEqual(manager.rooms["owner1"]["pending_disconnects"], {})

    def test_clear_room_pending_disconnect(self):
        manager = DummyReconnectManager()
        set_room_pending_disconnect(manager, "owner1", "c1", "Alice", "team-left", 111.0)
        clear_room_pending_disconnect(manager, "owner1", "c1")
        self.assertEqual(manager.rooms["owner1"]["pending_disconnects"], {})


if __name__ == "__main__":
    unittest.main()

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from backend.account_auth import AccountStore
from backend.account_auth import AccountAuthManager
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
from backend.storage import kifu_storage
from backend.server import QuizGameManager
from backend.schemas import (
    JudgeAnswerMessage,
    LegacyQuestionSubmissionMessage,
    OpenVoteResponseMessage,
    RoomEntryMessage,
    TurnEndVoteResponseMessage,
    validate_message,
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

        ticket_payload = manager.issue_ticket("Client_12345", "Alice", "user-1", "session-1")
        ticket = ticket_payload["ticket"]

        ok, reason, payload = manager.verify_ticket(ticket, "Client_12345")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertEqual(payload["user_id"], "user-1")
        self.assertEqual(payload["session_id"], "session-1")

        ok2, reason2, _ = manager.verify_ticket(ticket, "Client_12345")
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


class TestWebSocketSchemaContracts(unittest.TestCase):
    def test_vote_and_judge_boolean_strings_are_coerced(self):
        open_vote = validate_message(
            OpenVoteResponseMessage,
            {"type": "open_vote_response", "vote_id": "vote-1", "approve": "false"},
        )
        turn_end_vote = validate_message(
            TurnEndVoteResponseMessage,
            {"type": "turn_end_vote_response", "vote_id": "vote-2", "approve": "true"},
        )
        judge_answer = validate_message(
            JudgeAnswerMessage,
            {"type": "judge_answer", "is_correct": "false"},
        )

        self.assertFalse(open_vote.approve)
        self.assertTrue(turn_end_vote.approve)
        self.assertFalse(judge_answer.is_correct)

    def test_legacy_question_submission_still_validates_without_type(self):
        message = validate_message(
            LegacyQuestionSubmissionMessage,
            {"question_text": "テスト問題", "is_ai_mode": "true"},
        )

        self.assertEqual(message.type, "question_submission")
        self.assertEqual(message.question_text, "テスト問題")
        self.assertTrue(message.is_ai_mode)

    def test_room_entry_role_literal_is_validated(self):
        message = validate_message(
            RoomEntryMessage,
            {"type": "room_entry", "room_owner_id": "owner-1", "role": "spectator"},
        )

        self.assertEqual(message.role, "spectator")


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
        self.client_user_ids = {}
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
        self.assertEqual(reservation["kind"], "participant")  # type: ignore

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


class TestAccountStoreContracts(unittest.TestCase):
    def test_linked_client_ids_and_session_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = AccountStore(f"{tmp_dir}/auth_state.json")
            user = store.create_user(
                display_name="Alice",
                user_handle_b64="dXNlci1oYW5kbGU",
                credential_id="cred-1",
                public_key_b64="pub-1",
                sign_count=1,
            )
            linked = store.link_client_id(user["user_id"], "Client_12345")
            self.assertEqual(linked, ["Client_12345"])
            self.assertEqual(store.resolve_user_id_for_client_id("Client_12345"), user["user_id"])

            session_id = store.create_session(user["user_id"], "Client_12345")
            auth_user = store.build_authenticated_user(session_id)
            self.assertIsNotNone(auth_user)
            self.assertEqual(auth_user.user_id, user["user_id"])  # type: ignore[union-attr]
            self.assertEqual(auth_user.current_client_id, "Client_12345")  # type: ignore[union-attr]

    def test_record_match_result_updates_stats(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = AccountStore(f"{tmp_dir}/auth_state.json")
            left = store.create_user(
                display_name="Left",
                user_handle_b64="bGVmdA",
                credential_id="cred-left",
                public_key_b64="pub-left",
                sign_count=0,
            )
            right = store.create_user(
                display_name="Right",
                user_handle_b64="cmlnaHQ",
                credential_id="cred-right",
                public_key_b64="pub-right",
                sign_count=0,
            )

            store.record_match_result({left["user_id"]}, {right["user_id"]}, "team-left")

            left_after = store.get_user(left["user_id"])
            right_after = store.get_user(right["user_id"])
            self.assertEqual(left_after["stats"]["wins"], 1)  # type: ignore[index]
            self.assertEqual(right_after["stats"]["losses"], 1)  # type: ignore[index]

    def test_record_match_result_forced_loss_overrides_team_result(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = AccountStore(f"{tmp_dir}/auth_state.json")
            left_departed = store.create_user(
                display_name="LeftDeparted",
                user_handle_b64="bGVmdC1kZXBhcnRlZA",
                credential_id="cred-left-departed",
                public_key_b64="pub-left-departed",
                sign_count=0,
            )
            left_remaining = store.create_user(
                display_name="LeftRemain",
                user_handle_b64="bGVmdC1yZW1haW4",
                credential_id="cred-left-remain",
                public_key_b64="pub-left-remain",
                sign_count=0,
            )
            right = store.create_user(
                display_name="Right",
                user_handle_b64="cmlnaHQ",
                credential_id="cred-right",
                public_key_b64="pub-right",
                sign_count=0,
            )

            store.record_match_result(
                {left_departed["user_id"], left_remaining["user_id"]},
                {right["user_id"]},
                "team-left",
                forced_loss_user_ids={left_departed["user_id"]},
            )

            left_departed_after = store.get_user(left_departed["user_id"])
            left_remaining_after = store.get_user(left_remaining["user_id"])
            right_after = store.get_user(right["user_id"])
            self.assertEqual(left_departed_after["stats"]["losses"], 1)  # type: ignore[index]
            self.assertEqual(left_remaining_after["stats"]["wins"], 1)  # type: ignore[index]
            self.assertEqual(right_after["stats"]["losses"], 1)  # type: ignore[index]

    def test_finished_game_records_pending_reconnect_user_stats(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = AccountStore(f"{tmp_dir}/auth_state.json")
            left = store.create_user(
                display_name="Left",
                user_handle_b64="bGVmdA",
                credential_id="cred-left",
                public_key_b64="pub-left",
                sign_count=0,
            )
            right = store.create_user(
                display_name="Right",
                user_handle_b64="cmlnaHQ",
                credential_id="cred-right",
                public_key_b64="pub-right",
                sign_count=0,
            )

            manager = QuizGameManager()
            manager.account_auth_manager = AccountAuthManager(store)
            manager.rooms["owner-1"] = {
                "left_participants": {"left-client"},
                "right_participants": {"right-client"},
                "spectators": set(),
                "forced_loss_user_ids": set(),
                "game": {"winner": "team-left"},
                "game_state": "finished",
                "is_ai_mode": False,
                "questioner_id": "owner-1",
            }
            manager.client_user_ids["right-client"] = right["user_id"]
            manager.reconnect_reservations["left-client"] = {
                "kind": "participant",
                "room_owner_id": "owner-1",
                "team": "team-left",
                "user_id": left["user_id"],
                "nickname": "Left",
                "expires_at": 9999999999,
            }

            manager._record_finished_game_stats("owner-1", manager.rooms["owner-1"], "finished")

            left_after = store.get_user(left["user_id"])
            right_after = store.get_user(right["user_id"])
            self.assertEqual(left_after["stats"]["wins"], 1)  # type: ignore[index]
            self.assertEqual(right_after["stats"]["losses"], 1)  # type: ignore[index]

    def test_record_authored_match_updates_stats(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = AccountStore(f"{tmp_dir}/auth_state.json")
            author = store.create_user(
                display_name="Author",
                user_handle_b64="YXV0aG9y",
                credential_id="cred-author",
                public_key_b64="pub-author",
                sign_count=0,
            )

            store.record_authored_match(author["user_id"])

            author_after = store.get_user(author["user_id"])
            self.assertEqual(author_after["stats"]["questions_authored"], 1)  # type: ignore[index]

    def test_update_user_display_name_updates_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = AccountStore(f"{tmp_dir}/auth_state.json")
            user = store.create_user(
                display_name="Before",
                user_handle_b64="YmVmb3Jl",
                credential_id="cred-before",
                public_key_b64="pub-before",
                sign_count=0,
            )

            updated = store.update_user_display_name(user["user_id"], "After")

            self.assertEqual(updated["display_name"], "After")
            refreshed = store.get_user(user["user_id"])
            self.assertEqual(refreshed["display_name"], "After")  # type: ignore[index]

    def test_can_link_client_id_blocks_other_users(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = AccountStore(f"{tmp_dir}/auth_state.json")
            owner = store.create_user(
                display_name="Owner",
                user_handle_b64="b3duZXI",
                credential_id="cred-owner",
                public_key_b64="pub-owner",
                sign_count=0,
            )
            other = store.create_user(
                display_name="Other",
                user_handle_b64="b3RoZXI",
                credential_id="cred-other",
                public_key_b64="pub-other",
                sign_count=0,
            )
            store.link_client_id(owner["user_id"], "Client_12345")

            self.assertTrue(store.can_link_client_id(owner["user_id"], "Client_12345"))
            self.assertFalse(store.can_link_client_id(other["user_id"], "Client_12345"))

    def test_expired_session_is_not_returned(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = AccountStore(f"{tmp_dir}/auth_state.json")
            user = store.create_user(
                display_name="Alice",
                user_handle_b64="YWxpY2U",
                credential_id="cred-alice",
                public_key_b64="pub-alice",
                sign_count=0,
            )
            session_id = store.create_session(user["user_id"], "Client_12345")

            with store._lock:  # type: ignore[attr-defined]
                store._state["sessions"][session_id]["expires_at"] = 1  # type: ignore[attr-defined]
                store._persist_locked()  # type: ignore[attr-defined]

            self.assertIsNone(store.get_session(session_id, touch=False))


class DummyCookieRequest:
    def __init__(self, scheme="http", headers=None, hostname="example.com", port=None):
        self.headers = headers or {}
        self.cookies = {}
        self.base_url = f"{scheme}://{hostname}"
        self.url = type(
            "DummyUrl",
            (),
            {
                "scheme": scheme,
                "hostname": hostname,
                "port": port,
            },
        )()


class DummyCookieResponse:
    def __init__(self):
        self.cookies = []

    def set_cookie(self, *args, **kwargs):
        self.cookies.append(kwargs)

    def delete_cookie(self, *args, **kwargs):
        pass


class TestAccountAuthSecurityContracts(unittest.TestCase):
    def test_session_cookie_secure_uses_https_request_scheme(self):
        manager = AccountAuthManager()
        request = DummyCookieRequest(scheme="https")

        with patch.dict("os.environ", {}, clear=False):
            self.assertTrue(manager._should_secure_session_cookie(request))

    def test_session_cookie_secure_trusts_forwarded_proto_when_enabled(self):
        manager = AccountAuthManager()
        request = DummyCookieRequest(
            scheme="http",
            headers={"x-forwarded-proto": "https"},
        )

        with patch.dict("os.environ", {"QUIZ_TRUST_PROXY_HEADERS": "1"}, clear=False):
            self.assertTrue(manager._should_secure_session_cookie(request))

    def test_session_cookie_secure_can_be_forced_with_env(self):
        manager = AccountAuthManager()
        request = DummyCookieRequest(scheme="http")

        with patch.dict("os.environ", {"QUIZ_SESSION_COOKIE_SECURE": "always"}, clear=False):
            self.assertTrue(manager._should_secure_session_cookie(request))

    def test_set_session_cookie_applies_secure_flag_from_helper(self):
        manager = AccountAuthManager()
        request = DummyCookieRequest(
            scheme="http",
            headers={"x-forwarded-proto": "https"},
        )
        response = DummyCookieResponse()

        with patch.dict("os.environ", {"QUIZ_TRUST_PROXY_HEADERS": "1"}, clear=False):
            manager._set_session_cookie(response, "session-1", request)

        self.assertEqual(len(response.cookies), 1)
        self.assertTrue(response.cookies[0]["secure"])


class TestKifuIdentityContracts(unittest.TestCase):
    def test_list_kifu_for_identity_accepts_legacy_client_links(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            original_dir = kifu_storage.KIFU_DIR
            kifu_storage.KIFU_DIR = tmp_dir
            try:
                room = {
                    "question_text": "テスト問題",
                    "left_participants": {"legacy-client"},
                    "right_participants": set(),
                    "spectators": set(),
                    "game": {"winner": "team-left", "game_status": "finished", "team_left": {}, "team_right": {}, "opened_char_indexes": set()},
                }
                nicknames = {"owner-client": "出題者", "legacy-client": "参加者"}
                client_user_ids = {"owner-client": "user-owner"}
                kifu_id = kifu_storage.begin_kifu_record("owner-client", room, nicknames, client_user_ids)
                kifu_storage.finalize_kifu_record(kifu_id, room, "finished")

                rows = kifu_storage.list_kifu_for_identity("user-participant", {"legacy-client"})
                self.assertEqual(len(rows), 1)
                detail = kifu_storage.get_kifu_detail_for_identity(kifu_id, "user-participant", {"legacy-client"})
                self.assertIsNotNone(detail)
                self.assertEqual(detail["your_role"], "participant")  # type: ignore[index]
            finally:
                kifu_storage.KIFU_DIR = original_dir


class TestAiFullOpenSettlementContracts(unittest.TestCase):
    def test_ai_full_open_settlement_auto_judges_both_answers(self):
        manager = QuizGameManager()
        manager.broadcast_state = AsyncMock()
        manager._broadcast_game_finished_message = AsyncMock()
        manager._finalize_kifu_if_tracking = lambda *args, **kwargs: None
        room = {
            "game_state": "playing",
            "is_ai_mode": True,
            "ai_expected_answer": "富士山",
            "left_participants": {"left-client"},
            "right_participants": {"right-client"},
            "spectators": set(),
            "game": {
                "full_open_settlement": {
                    "state": "judging",
                    "vote_id": "vote-1",
                    "answers": {
                    "team-left": "富士山",
                    "team-right": "高尾山",
                    },
                }
            }
        }
        manager.rooms["owner-1"] = room

        with patch("backend.server.check_answer_async", side_effect=[True, False]):
            asyncio.run(
                manager._resolve_ai_full_open_settlement_judgement(
                    "owner-1",
                    room,
                )
            )

        self.assertEqual(room["game_state"], "finished")
        self.assertEqual(room["game"]["winner"], "team-left")
        self.assertEqual(
            room["game"]["full_open_settlement"]["judgements"],
            {"team-left": True, "team-right": False},
        )
        manager._broadcast_game_finished_message.assert_awaited_once()

    def test_ai_full_open_settlement_missing_expected_answer_notifies_and_stops(self):
        manager = QuizGameManager()
        manager._judge_full_open_settlement_impl = AsyncMock()
        manager.broadcast_state = AsyncMock()
        room = {
            "game_state": "playing",
            "is_ai_mode": True,
            "ai_expected_answer": "",
            "left_participants": {"left-client"},
            "right_participants": {"right-client"},
            "spectators": {"spec-client"},
            "game": {
                "full_open_settlement": {
                    "state": "judging",
                    "vote_id": "vote-2",
                    "answers": {
                        "team-left": "A",
                        "team-right": "B",
                    },
                }
            },
        }

        asyncio.run(
            manager._resolve_ai_full_open_settlement_judgement(
                "owner-1",
                room,
            )
        )

        manager._judge_full_open_settlement_impl.assert_not_awaited()
        manager.broadcast_state.assert_awaited_once()


class TestAiExpectedAnswerRevealContracts(unittest.TestCase):
    def test_ai_room_broadcasts_expected_answer_after_game_finished_once(self):
        manager = QuizGameManager()
        manager.broadcast_state = AsyncMock()
        room = {
            "is_ai_mode": True,
            "ai_expected_answer": "富士山",
            "left_participants": {"left-client"},
            "right_participants": {"right-client"},
            "spectators": {"spectator-client"},
        }

        asyncio.run(
            manager._broadcast_game_finished_message(
                "owner-1",
                room,
                "先攻の勝利です。",
            )
        )

        self.assertEqual(manager.broadcast_state.await_count, 2)
        first_call = manager.broadcast_state.await_args_list[0]
        second_call = manager.broadcast_state.await_args_list[1]
        self.assertEqual(first_call.kwargs["event_type"], "game_finished")
        self.assertEqual(second_call.kwargs["event_type"], "expected_answer_reveal")
        self.assertEqual(
            second_call.kwargs["event_message"],
            "想定正解は「富士山」でした。",
        )

        asyncio.run(
            manager._broadcast_game_finished_message(
                "owner-1",
                room,
                "先攻の勝利です。",
            )
        )

        self.assertEqual(manager.broadcast_state.await_count, 3)


if __name__ == "__main__":
    unittest.main()

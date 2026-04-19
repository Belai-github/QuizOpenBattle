from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import asyncio
import json
import os
import time
import uuid
from typing import Any, NamedTuple

from pydantic import ValidationError
from backend.account_auth import AccountAuthManager
from backend.auth import WebSocketAuthManager, is_valid_client_id, sanitize_nickname
from backend.events.formatting import (
    format_answer_attempt_message,
    format_answer_result_message,
    format_answer_vote_request_message,
    format_answer_vote_resolution_message,
    format_game_finished_message,
    format_intentional_draw_vote_resolution_message,
    format_open_vote_request_message,
    format_open_vote_resolution_message,
    format_turn_changed_message,
    format_turn_end_vote_request_message,
    format_turn_end_vote_resolution_message,
)
from backend.events.identity import derive_event_identity
from backend.events.masking import (
    mask_answer_text_for_viewer,
    resolve_event_message_for_client,
    resolve_event_payload_for_client,
)
from backend.storage.history import (
    append_arena_chat_history,
    append_lobby_chat_history,
    build_lobby_chat_history_snapshot,
    rebroadcast_finished_answer_logs,
    should_append_lobby_chat_history,
)
from backend.storage.reconnect import (
    clear_pending_disconnect_everywhere,
    clear_room_pending_disconnect,
    clear_room_reconnect_reservations,
    finalize_participant_disconnect_after_grace,
    purge_expired_reconnect_reservations,
    reserve_participant_reconnect,
    schedule_participant_disconnect_grace,
    set_room_pending_disconnect,
    try_restore_participant_reconnect,
)
from backend.broadcast import (
    broadcast_state as broadcast_state_handler,
    build_participants as build_participants_payload,
    build_rooms_summary as build_rooms_summary_payload,
    send_private_info as send_private_info_handler,
)
from backend.api_routes import register_api_routes
from backend.handlers.voting import (
    request_intentional_draw_vote as request_intentional_draw_vote_handler,
    request_open_vote as request_open_vote_handler,
    request_turn_end_attempt as request_turn_end_attempt_handler,
    respond_answer_vote as respond_answer_vote_handler,
    respond_intentional_draw_vote as respond_intentional_draw_vote_handler,
    respond_open_vote as respond_open_vote_handler,
    respond_turn_end_vote as respond_turn_end_vote_handler,
)
from backend.handlers.room_ops import (
    cancel_question as cancel_question_handler,
    join_room as join_room_handler,
    remove_client_from_all_rooms as remove_client_from_all_rooms_handler,
    shuffle_participants as shuffle_participants_handler,
    swap_participant_team as swap_participant_team_handler,
)
from backend.handlers.answering import (
    judge_answer as judge_answer_handler,
    judge_full_open_settlement as judge_full_open_settlement_handler,
    submit_answer_attempt as submit_answer_attempt_handler,
)
from backend.handlers.chat import process_chat_message as process_chat_message_handler
from backend.handlers.question import process_question as process_question_handler
from backend.schemas import (
    AnswerAttemptMessage,
    AnswerVoteResponseMessage,
    BaseMessage,
    CancelQuestionMessage,
    ChatMessage,
    FullOpenSettlementJudgeMessage,
    IntentionalDrawVoteRequestMessage,
    IntentionalDrawVoteResponseMessage,
    JudgeAnswerMessage,
    LegacyQuestionSubmissionMessage,
    OpenCharacterMessage,
    OpenVoteRequestMessage,
    OpenVoteResponseMessage,
    QuestionSubmissionMessage,
    RoomEntryMessage,
    RoomExitMessage,
    ShuffleParticipantsMessage,
    StartGameMessage,
    SubmitAnswerMessage,
    SwapParticipantTeamMessage,
    TurnEndAttemptMessage,
    TurnEndVoteResponseMessage,
    dump_message,
    validate_message,
)

from backend.game_logic import (
    _normalized_question_chars,
    apply_create_question_room,
    apply_exit_room,
    apply_join_room,
    apply_shuffle_participants,
    apply_swap_participant_team,
    apply_start_game,
    apply_open_character,
    apply_submit_answer,
    apply_end_turn,
    build_current_room_for_client,
    build_game_state_for_client,
    remove_client_from_all_rooms as remove_client_from_all_rooms_logic,
    resolve_chat_recipients,
    resolve_client_room_context,
)
from backend.ai_logic import check_answer_async, generate_quiz_async, normalize_difficulty, normalize_model_id
from backend.storage.kifu_storage import (
    append_action,
    begin_kifu_record,
    finalize_kifu_record,
    resolve_latest_answer_result,
    touch_spectator,
)

app = FastAPI()

app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")


QUIZ_DIAG_API_ENABLED = os.getenv("QUIZ_DIAG_API", "").strip() == "1"


def diag_api_log(event: str, **fields):
    if not QUIZ_DIAG_API_ENABLED:
        return

    safe_fields = {str(k): v for k, v in fields.items()}
    print(f"[quiz-diag-api] {event} {json.dumps(safe_fields, ensure_ascii=False)}")


class MessageRoute(NamedTuple):
    model: type[BaseMessage]
    handler_name: str


MESSAGE_ROUTER: dict[str, MessageRoute] = {
    "room_exit": MessageRoute(RoomExitMessage, "exit_room"),
    "question_submission": MessageRoute(QuestionSubmissionMessage, "process_question"),
    "chat_message": MessageRoute(ChatMessage, "process_chat_message"),
    "start_game": MessageRoute(StartGameMessage, "start_game"),
    "shuffle_participants": MessageRoute(ShuffleParticipantsMessage, "shuffle_participants"),
    "swap_participant_team": MessageRoute(SwapParticipantTeamMessage, "swap_participant_team"),
    "open_character": MessageRoute(OpenCharacterMessage, "open_character"),
    "open_vote_request": MessageRoute(OpenVoteRequestMessage, "request_open_vote"),
    "open_vote_response": MessageRoute(OpenVoteResponseMessage, "respond_open_vote"),
    "answer_vote_response": MessageRoute(AnswerVoteResponseMessage, "respond_answer_vote"),
    "turn_end_vote_response": MessageRoute(TurnEndVoteResponseMessage, "respond_turn_end_vote"),
    "intentional_draw_vote_request": MessageRoute(IntentionalDrawVoteRequestMessage, "request_intentional_draw_vote"),
    "intentional_draw_vote_response": MessageRoute(IntentionalDrawVoteResponseMessage, "respond_intentional_draw_vote"),
    "submit_answer": MessageRoute(SubmitAnswerMessage, "submit_answer"),
    "answer_attempt": MessageRoute(AnswerAttemptMessage, "submit_answer_attempt"),
    "judge_answer": MessageRoute(JudgeAnswerMessage, "judge_answer"),
    "full_open_settlement_judge": MessageRoute(FullOpenSettlementJudgeMessage, "judge_full_open_settlement"),
    "end_turn": MessageRoute(TurnEndAttemptMessage, "request_turn_end_attempt"),
    "turn_end_attempt": MessageRoute(TurnEndAttemptMessage, "request_turn_end_attempt"),
    "room_entry": MessageRoute(RoomEntryMessage, "join_room"),
    "cancel_question": MessageRoute(CancelQuestionMessage, "cancel_question"),
}


class QuizGameManager:
    def __init__(self):
        self.active_connections = {}
        self.active_session_connections = {}
        self.nicknames = {}
        self.client_user_ids = {}
        self.client_session_ids = {}
        self.rooms = {}
        self.reconnect_reservations = {}
        self.pending_disconnect_tasks = {}
        self.MAX_CONNECTIONS = 10
        self.RECONNECT_RESERVATION_SECONDS = 120
        self.DISCONNECT_GRACE_SECONDS = 30
        self.CHAT_MAX_LENGTH = 200
        self.ANSWER_MAX_LENGTH = 100
        self.CHAT_MIN_INTERVAL_SECONDS = 0.8
        self.CHAT_RATE_WINDOW_SECONDS = 10.0
        self.CHAT_RATE_WINDOW_MAX_MESSAGES = 5
        self.chat_message_history = {}
        self.chat_last_message = {}
        self.lobby_chat_history = []
        self.lobby_chat_seq = 0
        self.active_kifu_by_room_owner = {}
        self.ai_question_generation_active = False
        self.ai_question_generation_owner_id = None
        self.ai_question_generation_lock = asyncio.Lock()
        self.account_auth_manager: AccountAuthManager | None = None

    def is_guest_client(self, client_id: str) -> bool:
        return str(self.client_user_ids.get(client_id) or "").strip() == ""

    def _has_active_ai_room(self):
        return any(bool(room.get("is_ai_mode")) for room in self.rooms.values())

    def _start_kifu_tracking(self, room_owner_id: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            return

        kifu_id = begin_kifu_record(room_owner_id, room, self.nicknames, self.client_user_ids)
        self.active_kifu_by_room_owner[room_owner_id] = kifu_id
        room["kifu_id"] = kifu_id

    def _append_kifu_action(self, room_owner_id: str, action_type: str, team: str, actor_id: str, payload: dict | None = None):
        kifu_id = self.active_kifu_by_room_owner.get(room_owner_id)
        if not kifu_id:
            return

        append_action(
            kifu_id,
            {
                "action_type": action_type,
                "team": str(team or ""),
                "actor_id": str(actor_id or ""),
                "actor_name": self.nicknames.get(actor_id, "ゲスト"),
                "payload": payload if isinstance(payload, dict) else {},
                "timestamp": int(time.time() * 1000),
            },
        )

    def _touch_kifu_spectator_if_tracking(self, room_owner_id: str, client_id: str):
        kifu_id = self.active_kifu_by_room_owner.get(room_owner_id)
        if not kifu_id:
            return

        touch_spectator(
            kifu_id,
            client_id,
            self.nicknames.get(client_id, "ゲスト"),
            self.client_user_ids.get(client_id),
        )

    def _resolve_kifu_latest_answer(self, room_owner_id: str, team: str, answer_text: str, is_correct: bool):
        kifu_id = self.active_kifu_by_room_owner.get(room_owner_id)
        if not kifu_id:
            return

        resolve_latest_answer_result(kifu_id, team, answer_text, is_correct)

    def _finalize_kifu_if_tracking(self, room_owner_id: str, room: dict | None, finish_reason: str):
        kifu_id = self.active_kifu_by_room_owner.pop(room_owner_id, None)
        if not kifu_id:
            return

        if isinstance(room, dict):
            self._record_finished_game_stats(room_owner_id, room, finish_reason)
        finalize_kifu_record(kifu_id, room, finish_reason)

    def _mark_forced_loss_user_id(self, room: dict | None, user_id: str | None, team: str | None):
        if not isinstance(room, dict):
            return
        if str(room.get("game_state") or "") != "playing":
            return
        if str(team or "") not in {"team-left", "team-right"}:
            return

        resolved_user_id = str(user_id or "").strip()
        if resolved_user_id == "":
            return

        raw_forced_losses = room.get("forced_loss_user_ids")
        if isinstance(raw_forced_losses, set):
            forced_loss_user_ids = raw_forced_losses
        elif isinstance(raw_forced_losses, (list, tuple)):
            forced_loss_user_ids = {
                str(item or "").strip()
                for item in raw_forced_losses
                if str(item or "").strip() != ""
            }
            room["forced_loss_user_ids"] = forced_loss_user_ids
        else:
            forced_loss_user_ids = set()
            room["forced_loss_user_ids"] = forced_loss_user_ids

        forced_loss_user_ids.add(resolved_user_id)

    def _collect_finished_room_team_user_ids(self, room_owner_id: str, room: dict) -> tuple[set[str], set[str]]:
        team_left_user_ids = {
            str(self.client_user_ids.get(client_id) or "").strip()
            for client_id in set(room.get("left_participants", set()))
            if str(self.client_user_ids.get(client_id) or "").strip() != ""
        }
        team_right_user_ids = {
            str(self.client_user_ids.get(client_id) or "").strip()
            for client_id in set(room.get("right_participants", set()))
            if str(self.client_user_ids.get(client_id) or "").strip() != ""
        }

        for reservation in self.reconnect_reservations.values():
            if not isinstance(reservation, dict):
                continue
            if str(reservation.get("kind") or "") != "participant":
                continue
            if str(reservation.get("room_owner_id") or "") != str(room_owner_id or ""):
                continue

            reserved_user_id = str(reservation.get("user_id") or "").strip()
            reserved_team = str(reservation.get("team") or "").strip()
            if reserved_user_id == "":
                continue

            if reserved_team == "team-left":
                team_left_user_ids.add(reserved_user_id)
            elif reserved_team == "team-right":
                team_right_user_ids.add(reserved_user_id)

        return team_left_user_ids, team_right_user_ids

    def _record_finished_game_stats(self, room_owner_id: str, room: dict, finish_reason: str):
        if self.account_auth_manager is None:
            return
        if str(finish_reason or "") not in {"finished", "forfeit", "intentional_draw"}:
            return

        game_value = room.get("game")
        game = game_value if isinstance(game_value, dict) else {}
        winner = str(game.get("winner") or "")
        if winner not in {"team-left", "team-right", "draw"}:
            return

        team_left_user_ids, team_right_user_ids = self._collect_finished_room_team_user_ids(room_owner_id, room)
        raw_forced_loss_user_ids = room.get("forced_loss_user_ids")
        if isinstance(raw_forced_loss_user_ids, set):
            forced_loss_user_ids = {
                str(user_id or "").strip()
                for user_id in raw_forced_loss_user_ids
                if str(user_id or "").strip() != ""
            }
        elif isinstance(raw_forced_loss_user_ids, (list, tuple)):
            forced_loss_user_ids = {
                str(user_id or "").strip()
                for user_id in raw_forced_loss_user_ids
                if str(user_id or "").strip() != ""
            }
        else:
            forced_loss_user_ids = set()

        self.account_auth_manager.store.record_match_result(
            {user_id for user_id in team_left_user_ids if user_id != ""},
            {user_id for user_id in team_right_user_ids if user_id != ""},
            winner,
            forced_loss_user_ids=forced_loss_user_ids,
        )

        if bool(room.get("is_ai_mode")):
            return

        questioner_client_id = str(room.get("questioner_id") or "").strip()
        questioner_user_id = str(self.client_user_ids.get(questioner_client_id) or "").strip()
        if questioner_user_id != "":
            self.account_auth_manager.store.record_authored_match(questioner_user_id)

    def _next_room_event_id(self, room_owner_id: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            return str(uuid.uuid4())

        seq = int(room.get("arena_event_id_seq", 0)) + 1
        room["arena_event_id_seq"] = seq
        return f"{room_owner_id}:evt:{seq}"

    def _derive_event_identity(
        self,
        event_room_id: str | None,
        event_type: str | None,
        event_chat_type: str | None,
        event_payload: dict | None,
    ):
        return derive_event_identity(
            event_room_id,
            event_type,
            event_chat_type,
            event_payload,
            self.rooms,
            self._next_room_event_id,
        )

    def build_participants(self):
        return build_participants_payload(self.nicknames)

    def build_rooms_summary(self, viewer_client_id: str | None = None):
        return build_rooms_summary_payload(self.rooms, self.nicknames, viewer_client_id)

    def build_current_room_for_client(self, client_id: str):
        return build_current_room_for_client(self.rooms, self.nicknames, client_id)

    def _room_member_ids(self, room_owner_id: str, room: dict) -> set[str]:
        return {room_owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))

    async def _finalize_answer_judgement(self, owner_id: str, room: dict, team: str, answer_text: str, is_correct: bool):
        game = room.get("game") or {}
        previous_turn_team = game.get("current_turn_team")
        game["pending_answer_judgement"] = None
        result = apply_submit_answer(room, team, is_correct)

        if not result.get("ok"):
            return result

        self._resolve_kifu_latest_answer(owner_id, team, answer_text, is_correct)

        left_ids = set(room.get("left_participants", set()))
        right_ids = set(room.get("right_participants", set()))
        spectator_ids = set(room.get("spectators", set()))
        questioner_ids = {owner_id}

        private_map = {}

        if is_correct:
            if team == "team-left":
                msg = "先攻が正解しました。次の後攻のターンで正解できれば引き分け、そうでなければ先攻の勝利です。"
                for target_id in left_ids | right_ids | spectator_ids | questioner_ids:
                    private_map[target_id] = msg
            else:
                winner = result.get("winner")
                if winner == "draw":
                    msg = "後攻が正解しました。引き分けです。"
                else:
                    msg = "後攻が正解しました。後攻の勝利です。"
                for target_id in left_ids | right_ids | spectator_ids | questioner_ids:
                    private_map[target_id] = msg
        else:
            if result.get("game_status") == "finished" and result.get("winner") == "team-left":
                end_msg = "後攻が正解できませんでした。先攻の勝利です。"
                for target_id in left_ids | right_ids | spectator_ids | questioner_ids:
                    private_map[target_id] = end_msg
            else:
                self_msg = "誤答です。相手に＋アクション権が1回付与されます"
                other_msg = "相手が誤答しました。＋アクション権を1回獲得しました。"

                if team == "team-left":
                    for target_id in left_ids:
                        private_map[target_id] = self_msg
                    for target_id in right_ids:
                        private_map[target_id] = other_msg
                else:
                    for target_id in right_ids:
                        private_map[target_id] = self_msg
                    for target_id in left_ids:
                        private_map[target_id] = other_msg

        if private_map:
            await self.broadcast_state(
                public_info="正誤判定が完了しました。",
                private_map=private_map,
                event_type="private_notice",
                event_room_id=owner_id,
            )

        team_label = self._team_label(team)
        await self._broadcast_team_log_message(
            owner_id,
            room,
            "answer_result",
            self._format_answer_result_message(team_label, is_correct),
            event_payload={
                "team": team,
            },
        )

        next_turn_team = (room.get("game") or {}).get("current_turn_team")
        should_notify_turn_changed = result.get("game_status") == "playing" and previous_turn_team != next_turn_team
        if should_notify_turn_changed:
            turn_changed_message = self._format_turn_changed_message(next_turn_team)
            await self.broadcast_state(
                public_info=turn_changed_message,
                event_type="turn_changed",
                event_room_id=owner_id,
            )
            await self._broadcast_team_log_message(owner_id, room, "turn_changed", turn_changed_message)

        if result.get("game_status") == "finished":
            winner = result.get("winner")
            game_finished_message = self._format_game_finished_message(winner)
            await self._broadcast_game_finished_message(owner_id, room, game_finished_message)
            self._finalize_kifu_if_tracking(owner_id, room, "finished")

        return result

    async def _resolve_ai_answer_judgement(self, owner_id: str, room: dict, team: str, answer_text: str):
        game = room.get("game") or {}
        pending = game.get("pending_answer_judgement")
        if not pending:
            return

        expected_answer = str(room.get("ai_expected_answer", "")).strip()
        if expected_answer == "":
            game["pending_answer_judgement"] = None
            private_map = {target_id: "AI正誤判定に失敗しました。再度アンサーしてください。" for target_id in self._room_member_ids(owner_id, room)}
            await self.broadcast_state(
                public_info="AI正誤判定に失敗しました。",
                private_map=private_map,
                event_type="private_notice",
                event_room_id=owner_id,
            )
            return

        try:
            answer_judgement_result = check_answer_async(expected_answer, answer_text)
            if asyncio.iscoroutine(answer_judgement_result):
                is_correct = await asyncio.wait_for(answer_judgement_result, timeout=12.0)
            else:
                is_correct = bool(answer_judgement_result)
        except Exception:
            game["pending_answer_judgement"] = None
            private_map = {target_id: "AI正誤判定に失敗しました。再度アンサーしてください。" for target_id in self._room_member_ids(owner_id, room)}
            await self.broadcast_state(
                public_info="AI正誤判定に失敗しました。",
                private_map=private_map,
                event_type="private_notice",
                event_room_id=owner_id,
            )
            return

        result = await self._finalize_answer_judgement(owner_id, room, team, answer_text, bool(is_correct))
        if not result.get("ok"):
            private_map = {target_id: result.get("error", "AI正誤判定に失敗しました。") for target_id in self._room_member_ids(owner_id, room)}
            await self.broadcast_state(
                public_info="AI正誤判定に失敗しました。",
                private_map=private_map,
                event_type="private_notice",
                event_room_id=owner_id,
            )

    async def _resolve_ai_full_open_settlement_judgement(self, owner_id: str, room: dict):
        full_open = self._get_full_open_settlement_state(room)
        if not isinstance(full_open, dict):
            return

        if str(full_open.get("state") or "") != "judging":
            return

        expected_answer = str(room.get("ai_expected_answer", "")).strip()
        if expected_answer == "":
            private_map = {
                target_id: "AI正誤判定に失敗しました。必要に応じて手動で判定してください。"
                for target_id in self._room_member_ids(owner_id, room)
            }
            await self.broadcast_state(
                public_info="AI正誤判定に失敗しました。",
                private_map=private_map,
                event_type="private_notice",
                event_room_id=owner_id,
            )
            return

        answers = dict(full_open.get("answers") or {})
        left_answer_text = str(answers.get("team-left") or "").strip()
        right_answer_text = str(answers.get("team-right") or "").strip()
        if left_answer_text == "" or right_answer_text == "":
            return

        async def _judge_answer_text(answer_text: str) -> bool:
            answer_judgement_result = check_answer_async(expected_answer, answer_text)
            if asyncio.iscoroutine(answer_judgement_result):
                return bool(await asyncio.wait_for(answer_judgement_result, timeout=12.0))
            return bool(answer_judgement_result)

        try:
            left_is_correct, right_is_correct = await asyncio.gather(
                _judge_answer_text(left_answer_text),
                _judge_answer_text(right_answer_text),
            )
        except Exception:
            private_map = {
                target_id: "AI正誤判定に失敗しました。必要に応じて手動で判定してください。"
                for target_id in self._room_member_ids(owner_id, room)
            }
            await self.broadcast_state(
                public_info="AI正誤判定に失敗しました。",
                private_map=private_map,
                event_type="private_notice",
                event_room_id=owner_id,
            )
            return

        await self._judge_full_open_settlement_impl(
            owner_id,
            str(full_open.get("vote_id") or ""),
            bool(left_is_correct),
            bool(right_is_correct),
        )

    async def broadcast_state(
        self,
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
        return await broadcast_state_handler(
            self,
            public_info,
            private_map=private_map,
            event_type=event_type,
            event_message=event_message,
            event_chat_type=event_chat_type,
            event_room_id=event_room_id,
            target_screen=target_screen,
            event_recipient_ids=event_recipient_ids,
            event_payload=event_payload,
        )

    def _resolve_team_for_client(self, room: dict, client_id: str):
        if client_id in room["left_participants"]:
            return "team-left"
        if client_id in room["right_participants"]:
            return "team-right"
        return None

    def _get_team_participant_ids(self, room: dict, team: str):
        if team == "team-left":
            return set(room["left_participants"])
        if team == "team-right":
            return set(room["right_participants"])
        return set()

    def _team_label(self, team: str):
        if team == "team-left":
            return "先攻"
        if team == "team-right":
            return "後攻"
        return ""

    # 以下、イベントメッセージのフォーマット関数

    def _format_turn_changed_message(self, next_turn_team: str | None):
        return format_turn_changed_message(next_turn_team)

    def _format_open_vote_request_message(self, requester_name: str, char_index: int, should_emit_vote_log: bool):
        return format_open_vote_request_message(requester_name, char_index, should_emit_vote_log)

    def _format_open_vote_resolution_message(self, team_label: str, char_index: int, approved: bool):
        return format_open_vote_resolution_message(team_label, char_index, approved)

    def _format_answer_attempt_message(self, team_label: str, answer_text: str):
        return format_answer_attempt_message(team_label, answer_text)

    def _format_answer_vote_request_message(self, requester_name: str, answer_text: str, should_emit_vote_log: bool):
        return format_answer_vote_request_message(requester_name, answer_text, should_emit_vote_log)

    def _format_answer_vote_resolution_message(self, team_label: str, answer_text: str, approved: bool, should_emit_vote_log: bool):
        return format_answer_vote_resolution_message(team_label, answer_text, approved, should_emit_vote_log)

    def _format_turn_end_vote_request_message(self, requester_name: str, should_emit_vote_log: bool):
        return format_turn_end_vote_request_message(requester_name, should_emit_vote_log)

    def _format_turn_end_vote_resolution_message(self, approved: bool):
        return format_turn_end_vote_resolution_message(approved)

    def _format_intentional_draw_vote_resolution_message(self, approved: bool):
        return format_intentional_draw_vote_resolution_message(approved)

    def _start_full_open_settlement(self, room: dict, vote_id: str, requester_id: str):
        game = room.get("game") or {}
        raw_team_left = game.get("team_left")
        team_left = raw_team_left if isinstance(raw_team_left, dict) else {}
        raw_team_right = game.get("team_right")
        team_right = raw_team_right if isinstance(raw_team_right, dict) else {}
        team_left["action_points"] = 1
        team_left["bonus_action_points"] = 0
        team_right["action_points"] = 1
        team_right["bonus_action_points"] = 0
        game["team_left"] = team_left
        game["team_right"] = team_right

        game["full_open_settlement"] = {
            "state": "answering",
            "vote_id": vote_id,
            "submitted_teams": [],
            "answers": {
                "team-left": None,
                "team-right": None,
            },
            "judgements": {
                "team-left": None,
                "team-right": None,
            },
            "final_winner": None,
            "requester_id": requester_id,
        }

    def _get_full_open_settlement_state(self, room: dict):
        game = room.get("game") or {}
        state = game.get("full_open_settlement")
        return state if isinstance(state, dict) else None

    def _format_answer_result_message(self, team_label: str, is_correct: bool):
        return format_answer_result_message(team_label, is_correct)

    def _format_game_finished_message(self, winner: str | None):
        return format_game_finished_message(winner)

    def _mask_answer_text_for_viewer(self, message: str):
        return mask_answer_text_for_viewer(message)

    def _is_intentional_draw_eligible(self, room: dict):
        if not isinstance(room, dict):
            return False

        if room.get("game_state") != "playing":
            return False

        game = room.get("game") or {}
        full_open = game.get("full_open_settlement")
        if isinstance(full_open, dict) and str(full_open.get("state") or "idle") != "idle":
            return False

        if game.get("game_status") != "playing":
            return False

        question_length = len(_normalized_question_chars(room.get("question_text", "")))
        if question_length <= 0:
            return False

        opened_count = len(game.get("opened_char_indexes", set()) or set())
        if (opened_count / question_length) < 0.7:
            return False

        left_wrong_count = int(((game.get("team_left") or {}).get("wrong_answer_count") or 0))
        right_wrong_count = int(((game.get("team_right") or {}).get("wrong_answer_count") or 0))
        return left_wrong_count >= 1 and right_wrong_count >= 1

    def _resolve_event_message_for_client(
        self,
        current_room: dict | None,
        event_type: str | None,
        event_chat_type: str | None,
        event_message: str,
        event_payload: dict | None,
    ):
        return resolve_event_message_for_client(current_room, event_type, event_chat_type, event_message, event_payload)

    def _resolve_event_payload_for_client(
        self,
        current_room: dict | None,
        event_type: str | None,
        event_chat_type: str | None,
        event_payload: dict | None,
    ):
        return resolve_event_payload_for_client(current_room, event_type, event_chat_type, event_payload)

    async def _rebroadcast_finished_answer_logs(self, room_owner_id: str):
        await rebroadcast_finished_answer_logs(self, room_owner_id)

    # 以下、内部処理関数

    def _should_append_lobby_chat_history(self, event_type: str | None, event_chat_type: str | None, event_room_id: str | None):
        return should_append_lobby_chat_history(event_type, event_chat_type, event_room_id)

    def _append_lobby_chat_history(
        self,
        event_type: str,
        event_message: str,
        event_chat_type: str,
        event_identity: dict | None = None,
        log_marker_id: str | None = None,
        event_timestamp: int | None = None,
    ):
        append_lobby_chat_history(
            self,
            event_type,
            event_message,
            event_chat_type,
            event_identity=event_identity,
            log_marker_id=log_marker_id,
            event_timestamp=event_timestamp,
        )

    def _build_lobby_chat_history_snapshot(self):
        return build_lobby_chat_history_snapshot(self)

    def _append_arena_chat_history(
        self,
        room_owner_id: str,
        event_type: str,
        event_message: str,
        event_chat_type: str,
        log_marker_id: str | None = None,
        event_identity: dict | None = None,
        event_payload: dict | None = None,
        event_timestamp: int | None = None,
    ):
        append_arena_chat_history(
            self,
            room_owner_id,
            event_type,
            event_message,
            event_chat_type,
            log_marker_id=log_marker_id,
            event_identity=event_identity,
            event_payload=event_payload,
            event_timestamp=event_timestamp,
        )

    def _cancel_disconnect_grace_timer(self, client_id: str):
        task = self.pending_disconnect_tasks.pop(client_id, None)
        if task is not None and not task.done():
            task.cancel()

    def _set_room_pending_disconnect(
        self,
        room_owner_id: str,
        client_id: str,
        nickname: str,
        team: str,
        expires_at: float,
    ):
        set_room_pending_disconnect(self, room_owner_id, client_id, nickname, team, expires_at)

    def _clear_room_pending_disconnect(self, room_owner_id: str, client_id: str):
        clear_room_pending_disconnect(self, room_owner_id, client_id)

    def _clear_pending_disconnect_everywhere(self, client_id: str):
        clear_pending_disconnect_everywhere(self, client_id)

    def _purge_expired_reconnect_reservations(self):
        purge_expired_reconnect_reservations(self)

    def _clear_room_reconnect_reservations(self, room_owner_id: str):
        clear_room_reconnect_reservations(self, room_owner_id)

    def _is_owner_joined_as_guest(self, room_owner_id: str, room: dict | None = None) -> bool:
        target_room = room if isinstance(room, dict) else self.rooms.get(room_owner_id)
        if target_room is None:
            return False

        return room_owner_id in target_room.get("left_participants", set()) or room_owner_id in target_room.get("right_participants", set()) or room_owner_id in target_room.get("spectators", set())

    def _reserve_participant_reconnect(self, client_id: str, ctx: dict | None):
        return reserve_participant_reconnect(self, client_id, ctx)

    def _try_restore_participant_reconnect(self, client_id: str):
        return try_restore_participant_reconnect(self, client_id)

    async def _evaluate_team_forfeit_if_needed(self, room_owner_id: str, room: dict):
        if room.get("game_state") != "playing":
            return

        game = room.get("game") or {}
        if game.get("game_status") != "playing":
            return

        left_count = len(room.get("left_participants", set()))
        right_count = len(room.get("right_participants", set()))
        if left_count > 0 and right_count > 0:
            return

        if left_count == 0 and right_count == 0:
            winner = None
            winner_label = "引き分け"
            notice_message = "両陣営の参加者が0人になったため、引き分けで終了しました。"
        elif left_count == 0:
            winner = "team-right"
            winner_label = "後攻"
            notice_message = "先攻の参加者が0人になったため、後攻の勝利です。"
        else:
            winner = "team-left"
            winner_label = "先攻"
            notice_message = "後攻の参加者が0人になったため、先攻の勝利です。"

        game["game_status"] = "finished"
        game["winner"] = winner
        game["pending_answer_judgement"] = None
        room["game_state"] = "finished"
        room["pending_open_vote"] = None
        room["pending_answer_vote"] = None
        room["pending_turn_end_vote"] = None
        room["pending_intentional_draw_vote"] = None

        recipients = {room_owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))
        private_map = {target_id: notice_message for target_id in recipients}

        await self.broadcast_state(
            public_info="人数不足によりゲームを終了しました。",
            private_map=private_map,
            event_type="private_notice",
            event_room_id=room_owner_id,
        )
        game_finished_message = self._format_game_finished_message(winner)
        await self._broadcast_game_finished_message(room_owner_id, room, game_finished_message)
        self._finalize_kifu_if_tracking(room_owner_id, room, "forfeit")

    async def _finalize_participant_disconnect_after_grace(
        self,
        client_id: str,
        room_owner_id: str,
        expires_at: float,
        nickname: str,
    ):
        return await finalize_participant_disconnect_after_grace(self, client_id, room_owner_id, expires_at, nickname)

    def _schedule_participant_disconnect_grace(
        self,
        client_id: str,
        room_owner_id: str,
        expires_at: float,
        nickname: str,
    ):
        return schedule_participant_disconnect_grace(self, client_id, room_owner_id, expires_at, nickname)

    async def _broadcast_team_log_message(self, owner_id: str, room: dict, event_type: str, message: str, event_payload: dict | None = None):
        for chat_type, default_ids in (
            ("team-left", set(room.get("left_participants", set()))),
            ("team-right", set(room.get("right_participants", set()))),
        ):
            recipient_ids = default_ids
            chat_result = resolve_chat_recipients(owner_id, room, "questioner", chat_type)
            if chat_result.get("ok"):
                recipient_ids = chat_result["event_recipient_ids"]

            if not recipient_ids:
                continue

            await self.broadcast_state(
                public_info="",
                event_type=event_type,
                event_message=message,
                event_chat_type=chat_type,
                event_room_id=owner_id,
                event_recipient_ids=recipient_ids,
                event_payload=event_payload,
            )

    async def _broadcast_turn_changed_logs(self, owner_id: str, room: dict, message: str):
        await self._broadcast_team_log_message(owner_id, room, "turn_changed", message)

    async def _broadcast_ai_expected_answer_reveal(self, owner_id: str, room: dict, recipient_ids: set[str] | None = None):
        if not bool(room.get("is_ai_mode")):
            return

        if bool(room.get("ai_expected_answer_revealed")):
            return

        expected_answer = str(room.get("ai_expected_answer", "")).strip()
        if expected_answer == "":
            return

        all_recipient_ids = (
            set(recipient_ids)
            if isinstance(recipient_ids, set)
            else self._room_member_ids(owner_id, room)
        )
        if not all_recipient_ids:
            return

        room["ai_expected_answer_revealed"] = True
        reveal_marker_id = f"{owner_id}:ai_expected_answer"
        await self.broadcast_state(
            public_info="",
            event_type="expected_answer_reveal",
            event_message=f"想定正解は「{expected_answer}」でした。",
            event_chat_type="game-global",
            event_room_id=owner_id,
            event_recipient_ids=all_recipient_ids,
            event_payload={
                "expected_answer": expected_answer,
                "log_marker_id": reveal_marker_id,
                "event_id": reveal_marker_id,
            },
        )

    async def _broadcast_game_finished_message(self, owner_id: str, room: dict, message: str):
        """ゲーム終了ログをすべての参加者に1回だけ送信"""
        left_ids = set(room.get("left_participants", set()))
        right_ids = set(room.get("right_participants", set()))
        spectator_ids = set(room.get("spectators", set()))
        questioner_ids = {owner_id}

        # すべてのクライアントをセットでまとめて、重複を避ける
        all_recipient_ids = left_ids | right_ids | spectator_ids | questioner_ids

        await self.broadcast_state(
            public_info="",
            event_type="game_finished",
            event_message=message,
            event_chat_type="game-result",
            event_room_id=owner_id,
            event_recipient_ids=all_recipient_ids,
        )
        await self._broadcast_ai_expected_answer_reveal(owner_id, room, all_recipient_ids)

    async def _resend_pending_votes_to_client(self, room_owner_id: str, client_id: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            return

        if room.get("game_state") != "playing":
            return

        recipient_ids = {client_id}

        pending_open_vote = room.get("pending_open_vote")
        if isinstance(pending_open_vote, dict) and pending_open_vote.get("status") == "pending":
            voter_ids = set(pending_open_vote.get("voter_ids", set()))
            approved_ids = set(pending_open_vote.get("approved_ids", set()))
            rejected_ids = set(pending_open_vote.get("rejected_ids", set()))
            if client_id in voter_ids and client_id not in approved_ids and client_id not in rejected_ids:
                vote_id = str(pending_open_vote.get("vote_id") or "").strip()
                team = str(pending_open_vote.get("team") or "").strip()
                char_index = pending_open_vote.get("char_index")
                required_approvals = int(pending_open_vote.get("required_approvals") or 0)
                total_voters = len(voter_ids)
                if vote_id and team in {"team-left", "team-right"} and isinstance(char_index, int):
                    await self.broadcast_state(
                        public_info="",
                        event_type="open_vote_request",
                        event_message="",
                        event_chat_type=team,
                        event_room_id=room_owner_id,
                        event_recipient_ids=recipient_ids,
                        event_payload={
                            "vote_id": vote_id,
                            "team": team,
                            "char_index": char_index,
                            "required_approvals": required_approvals,
                            "total_voters": total_voters,
                            "log_marker_id": vote_id,
                            "skip_history": True,
                            "resend": True,
                        },
                    )

        pending_answer_vote = room.get("pending_answer_vote")
        if isinstance(pending_answer_vote, dict) and pending_answer_vote.get("status") == "pending":
            voter_ids = set(pending_answer_vote.get("voter_ids", set()))
            approved_ids = set(pending_answer_vote.get("approved_ids", set()))
            rejected_ids = set(pending_answer_vote.get("rejected_ids", set()))
            if client_id in voter_ids and client_id not in approved_ids and client_id not in rejected_ids:
                vote_id = str(pending_answer_vote.get("vote_id") or "").strip()
                team = str(pending_answer_vote.get("team") or "").strip()
                answer_text = str(pending_answer_vote.get("answer_text") or "").strip()
                requester_id = pending_answer_vote.get("requester_id")
                requester_name = self.nicknames.get(requester_id, "ゲスト")
                required_approvals = int(pending_answer_vote.get("required_approvals") or 0)
                total_voters = len(voter_ids)
                if vote_id and team in {"team-left", "team-right"}:
                    await self.broadcast_state(
                        public_info="",
                        event_type="answer_vote_request",
                        event_message="",
                        event_chat_type=team,
                        event_room_id=room_owner_id,
                        event_recipient_ids=recipient_ids,
                        event_payload={
                            "vote_id": vote_id,
                            "team": team,
                            "team_label": self._team_label(team),
                            "answer_text": answer_text,
                            "answerer_name": requester_name,
                            "required_approvals": required_approvals,
                            "total_voters": total_voters,
                            "log_marker_id": vote_id,
                            "skip_history": True,
                            "resend": True,
                        },
                    )

        pending_turn_end_vote = room.get("pending_turn_end_vote")
        if isinstance(pending_turn_end_vote, dict) and pending_turn_end_vote.get("status") == "pending":
            voter_ids = set(pending_turn_end_vote.get("voter_ids", set()))
            approved_ids = set(pending_turn_end_vote.get("approved_ids", set()))
            rejected_ids = set(pending_turn_end_vote.get("rejected_ids", set()))
            if client_id in voter_ids and client_id not in approved_ids and client_id not in rejected_ids:
                vote_id = str(pending_turn_end_vote.get("vote_id") or "").strip()
                team = str(pending_turn_end_vote.get("team") or "").strip()
                required_approvals = int(pending_turn_end_vote.get("required_approvals") or 0)
                total_voters = len(voter_ids)
                if vote_id and team in {"team-left", "team-right"}:
                    await self.broadcast_state(
                        public_info="",
                        event_type="turn_end_vote_request",
                        event_message="",
                        event_chat_type=team,
                        event_room_id=room_owner_id,
                        event_recipient_ids=recipient_ids,
                        event_payload={
                            "vote_id": vote_id,
                            "team": team,
                            "team_label": self._team_label(team),
                            "required_approvals": required_approvals,
                            "total_voters": total_voters,
                            "log_marker_id": vote_id,
                            "skip_history": True,
                            "resend": True,
                        },
                    )

        pending_intentional_draw_vote = room.get("pending_intentional_draw_vote")
        if isinstance(pending_intentional_draw_vote, dict) and pending_intentional_draw_vote.get("status") == "pending":
            voter_ids = set(pending_intentional_draw_vote.get("voter_ids", set()))
            approved_ids = set(pending_intentional_draw_vote.get("approved_ids", set()))
            rejected_ids = set(pending_intentional_draw_vote.get("rejected_ids", set()))
            if client_id in voter_ids and client_id not in approved_ids and client_id not in rejected_ids:
                vote_id = str(pending_intentional_draw_vote.get("vote_id") or "").strip()
                required_approvals = int(pending_intentional_draw_vote.get("required_approvals") or 0)
                total_voters = len(voter_ids)
                requester_id = str(pending_intentional_draw_vote.get("requester_id") or "").strip()
                requester_name = self.nicknames.get(requester_id, "ゲスト")
                if vote_id:
                    await self.broadcast_state(
                        public_info="",
                        event_type="intentional_draw_vote_request",
                        event_message="",
                        event_chat_type="game-global",
                        event_room_id=room_owner_id,
                        event_recipient_ids=recipient_ids,
                        event_payload={
                            "vote_id": vote_id,
                            "required_approvals": required_approvals,
                            "total_voters": total_voters,
                            "requester_name": requester_name,
                            "log_marker_id": vote_id,
                            "skip_history": True,
                            "resend": True,
                        },
                    )

    async def _resend_pending_answer_judgement_to_client(self, room_owner_id: str, client_id: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            return

        if bool(room.get("is_ai_mode")):
            return

        if client_id != room_owner_id:
            return

        if room.get("game_state") != "playing":
            return

        game = room.get("game") or {}
        pending = game.get("pending_answer_judgement")
        if not isinstance(pending, dict):
            return

        team = str(pending.get("team") or "").strip()
        answer_text = str(pending.get("answer_text") or "").strip()
        answerer_id = str(pending.get("answerer_id") or "").strip()
        if team not in {"team-left", "team-right"}:
            return

        await self.broadcast_state(
            public_info="",
            event_type="answer_judgement_request",
            event_room_id=room_owner_id,
            event_recipient_ids={client_id},
            event_payload={
                "team": team,
                "team_label": self._team_label(team),
                "answer_text": answer_text,
                "answerer_name": self.nicknames.get(answerer_id, "参加者"),
                "resend": True,
            },
        )

    async def request_open_vote(self, client_id: str, payload: OpenVoteRequestMessage | int | None):
        message = payload if isinstance(payload, OpenVoteRequestMessage) else OpenVoteRequestMessage(type="open_vote_request", char_index=payload)
        return await request_open_vote_handler(self, client_id, message)

    async def respond_open_vote(self, client_id: str, payload: OpenVoteResponseMessage | dict[str, Any]):
        message = payload if isinstance(payload, OpenVoteResponseMessage) else validate_message(OpenVoteResponseMessage, payload)
        return await respond_open_vote_handler(self, client_id, message)

    async def respond_answer_vote(self, client_id: str, payload: AnswerVoteResponseMessage | dict[str, Any]):
        message = payload if isinstance(payload, AnswerVoteResponseMessage) else validate_message(AnswerVoteResponseMessage, payload)
        return await respond_answer_vote_handler(self, client_id, message)

    async def request_turn_end_attempt(self, client_id: str, payload: TurnEndAttemptMessage | None = None):
        message = payload if isinstance(payload, TurnEndAttemptMessage) else TurnEndAttemptMessage(type="turn_end_attempt")
        return await request_turn_end_attempt_handler(self, client_id, message)

    async def request_intentional_draw_vote(self, client_id: str, payload: IntentionalDrawVoteRequestMessage | None = None):
        message = (
            payload
            if isinstance(payload, IntentionalDrawVoteRequestMessage)
            else IntentionalDrawVoteRequestMessage(type="intentional_draw_vote_request")
        )
        return await request_intentional_draw_vote_handler(self, client_id, message)

    async def respond_intentional_draw_vote(self, client_id: str, payload: IntentionalDrawVoteResponseMessage | dict[str, Any]):
        message = (
            payload
            if isinstance(payload, IntentionalDrawVoteResponseMessage)
            else validate_message(IntentionalDrawVoteResponseMessage, payload)
        )
        return await respond_intentional_draw_vote_handler(self, client_id, message)

    async def respond_turn_end_vote(self, client_id: str, payload: TurnEndVoteResponseMessage | dict[str, Any]):
        message = payload if isinstance(payload, TurnEndVoteResponseMessage) else validate_message(TurnEndVoteResponseMessage, payload)
        return await respond_turn_end_vote_handler(self, client_id, message)

    async def send_private_info(
        self,
        client_id: str,
        message: str,
        target_screen: str | None = None,
        event_type: str = "private_notice",
    ):
        return await send_private_info_handler(
            self,
            client_id,
            message,
            target_screen=target_screen,
            event_type=event_type,
        )

    async def cancel_question(self, requester_id: str, payload: CancelQuestionMessage | str):
        message = payload if isinstance(payload, CancelQuestionMessage) else CancelQuestionMessage(type="cancel_question", room_owner_id=str(payload or "").strip())
        return await cancel_question_handler(self, requester_id, message)

    def remove_client_from_all_rooms(self, client_id: str):
        return remove_client_from_all_rooms_handler(self, client_id)

    async def join_room(self, client_id: str, payload: RoomEntryMessage | dict[str, Any]):
        message = payload if isinstance(payload, RoomEntryMessage) else validate_message(RoomEntryMessage, payload)
        return await join_room_handler(self, client_id, message)

    async def start_game(self, client_id: str, payload: StartGameMessage | dict[str, Any] | None = None):
        if isinstance(payload, StartGameMessage):
            payload_dict = dump_message(payload)
        elif isinstance(payload, dict):
            payload_dict = payload
        else:
            payload_dict = None

        result = apply_start_game(self.rooms, client_id, payload_dict)
        if not result.get("ok"):
            await self.send_private_info(client_id, result.get("error", "ゲーム開始に失敗しました。"))
            return

        room = self.rooms.get(client_id)
        if room is not None:
            room["arena_chat_history"] = []
            room["arena_chat_seq"] = 0
            # event_id は room 内で単調増加させて重複置換を防ぐ。
            room["finished_answer_logs_revealed"] = False
            room["pre_game_global_chat_history"] = []
            room["pre_game_global_chat_seq"] = 0
            self._start_kifu_tracking(client_id)

        questioner_name = result["questioner_name"]
        await self.broadcast_state(
            public_info=f"{questioner_name} がゲームを開始しました",
            event_type="game_start",
            event_message=f"{questioner_name} がゲームを開始しました",
            event_room_id=client_id,
        )

        await self.broadcast_state(
            public_info="",
            event_type="game_start",
            event_message="ゲームが開始されました。ゲーム中は進行ログに投稿されたチャットをプレイヤーは閲覧できません。",
            event_chat_type="game-global",
            event_room_id=client_id,
        )

    async def shuffle_participants(self, client_id: str, payload: ShuffleParticipantsMessage | None = None):
        return await shuffle_participants_handler(self, client_id)

    async def swap_participant_team(self, client_id: str, payload: SwapParticipantTeamMessage | str):
        message = (
            payload
            if isinstance(payload, SwapParticipantTeamMessage)
            else SwapParticipantTeamMessage(type="swap_participant_team", target_client_id=str(payload or "").strip())
        )
        return await swap_participant_team_handler(self, client_id, message)

    async def open_character(self, client_id: str, payload: OpenCharacterMessage | int | None):
        """文字をオープンするアクション"""
        char_index = payload.char_index if isinstance(payload, OpenCharacterMessage) else payload
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        if (room.get("game") or {}).get("pending_answer_judgement") is not None:
            await self.send_private_info(client_id, "正誤判定中は行動できません。")
            return

        full_open = self._get_full_open_settlement_state(room)
        if isinstance(full_open, dict) and str(full_open.get("state") or "idle") != "idle":
            await self.send_private_info(client_id, "フルオープン決着中は文字オープンできません。")
            return

        # チームを特定
        team = None
        if client_id in room["left_participants"]:
            team = "team-left"
        elif client_id in room["right_participants"]:
            team = "team-right"
        else:
            await self.send_private_info(client_id, "参加チームが見つかりません。")
            return

        # インデックスの型確認
        if not isinstance(char_index, int):
            await self.send_private_info(client_id, "無効な文字インデックスです。")
            return

        result = apply_open_character(room, team, char_index)
        if not result.get("ok"):
            await self.send_private_info(client_id, result.get("error", "文字をオープンできません。"))
            return

        is_yakumono = result.get("is_yakumono", False)
        message = f"{self.nicknames.get(client_id, '？')} が文字をオープンしました。{'（約物）' if is_yakumono else ''}"

        await self.broadcast_state(
            public_info=message,
            event_type="character_opened",
            event_room_id=owner_id,
        )

    async def submit_answer(self, client_id: str, payload: SubmitAnswerMessage | bool):
        """レガシーメソッド: 実際の判定処理はjudge_answer()に委譲"""
        message = payload if isinstance(payload, SubmitAnswerMessage) else SubmitAnswerMessage(type="submit_answer", is_correct=payload)
        await self.judge_answer(client_id, JudgeAnswerMessage(type="judge_answer", is_correct=message.is_correct))

    async def end_turn(self, client_id: str):
        """互換のため残す: 実体はターンエンド提案処理"""
        await self.request_turn_end_attempt(client_id)

    async def submit_answer_attempt(self, client_id: str, payload: AnswerAttemptMessage | str):
        message = payload if isinstance(payload, AnswerAttemptMessage) else AnswerAttemptMessage(type="answer_attempt", answer_text=str(payload or ""))
        return await submit_answer_attempt_handler(self, client_id, message)

    async def _submit_answer_attempt_impl(self, client_id: str, answer_text: str):
        """参加者が解答内容を提出するアクション"""
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        room_state = room.get("game_state", "waiting")
        if room_state != "playing":
            await self.send_private_info(client_id, "対戦中のみアンサーできます。")
            return

        game = room.get("game") or {}
        if game.get("pending_answer_judgement") is not None:
            await self.send_private_info(client_id, "現在、別の解答を正誤判定中です。")
            return

        pending_answer_vote = room.get("pending_answer_vote")
        if pending_answer_vote and pending_answer_vote.get("status") == "pending":
            await self.send_private_info(client_id, "現在、別のアンサー投票が進行中です。")
            return

        pending_turn_end_vote = room.get("pending_turn_end_vote")
        if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
            await self.send_private_info(client_id, "ターンエンド投票中は解答を送信できません。")
            return

        pending_open_vote = room.get("pending_open_vote")
        if pending_open_vote and pending_open_vote.get("status") == "pending":
            await self.send_private_info(client_id, "文字オープン投票中は解答を送信できません。")
            return

        pending_intentional_draw_vote = room.get("pending_intentional_draw_vote")
        if pending_intentional_draw_vote and pending_intentional_draw_vote.get("status") == "pending":
            await self.send_private_info(client_id, "フルオープン決着投票中は解答を送信できません。")
            return

        full_open_settlement = self._get_full_open_settlement_state(room)
        if not isinstance(full_open_settlement, dict):
            full_open_settlement = {}
        full_open_state = str(full_open_settlement.get("state") or "").strip()
        if full_open_state in {"answering", "judging"}:
            if client_id in room["left_participants"]:
                team = "team-left"
                team_label = "先攻"
            elif client_id in room["right_participants"]:
                team = "team-right"
                team_label = "後攻"
            else:
                await self.send_private_info(client_id, "参加者のみアンサーできます。")
                return

            if full_open_state != "answering":
                await self.send_private_info(client_id, "現在は判定待機中のため、追加のアンサーはできません。")
                return

            submitted_teams = list(full_open_settlement.get("submitted_teams") or [])
            if team in submitted_teams:
                await self.send_private_info(client_id, "この陣営はすでに回答済みです。")
                return

            text = str(answer_text or "").strip()
            if text == "":
                await self.send_private_info(client_id, "解答を入力してください。")
                return

            if len(text) > self.ANSWER_MAX_LENGTH:
                await self.send_private_info(
                    client_id,
                    f"解答は{self.ANSWER_MAX_LENGTH}文字以内で入力してください。",
                )
                return

            answers = dict(full_open_settlement.get("answers") or {})
            answers[team] = text
            if team not in submitted_teams:
                submitted_teams.append(team)

            full_open_settlement["answers"] = answers
            full_open_settlement["submitted_teams"] = submitted_teams

            self._append_kifu_action(
                owner_id,
                "answer",
                team,
                client_id,
                {
                    "answer_text": text,
                    "full_open_settlement": True,
                    "vote_id": str(full_open_settlement.get("vote_id") or ""),
                },
            )

            recipients = self._room_member_ids(owner_id, room)
            if len(submitted_teams) < 2:
                await self.broadcast_state(
                    public_info=f"{team_label}の回答が提出されました。",
                    private_map={client_id: f"{team_label}の回答を受け付けました。相手の回答を待っています。"},
                    event_type="full_open_settlement_answer",
                    event_message=f"{team_label}の回答が提出されました。",
                    event_room_id=owner_id,
                    event_recipient_ids=recipients,
                    event_payload={
                        "vote_id": str(full_open_settlement.get("vote_id") or ""),
                        "submitted_team": team,
                        "submitted_teams": submitted_teams,
                        "answers": answers,
                        "log_marker_id": str(full_open_settlement.get("vote_id") or ""),
                    },
                )
                return

            full_open_settlement["state"] = "judging"
            left_answer_text = str(answers.get("team-left") or "")
            right_answer_text = str(answers.get("team-right") or "")
            ready_message = f"先攻の解答は「{left_answer_text}」、後攻の解答は「{right_answer_text}」でした。"
            vote_marker_base = str(full_open_settlement.get("vote_id") or "").strip()
            ready_marker_id = f"{vote_marker_base}:ready" if vote_marker_base else str(uuid.uuid4())
            await self.broadcast_state(
                public_info="フルオープン決着の両陣営の回答がそろいました。判定してください。",
                event_type="full_open_settlement_ready",
                event_message=ready_message,
                event_chat_type="game-global",
                event_room_id=owner_id,
                event_recipient_ids=recipients,
                event_payload={
                    "vote_id": str(full_open_settlement.get("vote_id") or ""),
                    "answers": answers,
                    "submitted_teams": submitted_teams,
                    "log_marker_id": ready_marker_id,
                    "event_id": ready_marker_id,
                },
            )

            if room.get("is_ai_mode"):
                await self._resolve_ai_full_open_settlement_judgement(owner_id, room)
            return

        if client_id in room["left_participants"]:
            team = "team-left"
            team_label = "先攻"
        elif client_id in room["right_participants"]:
            team = "team-right"
            team_label = self._team_label(team)
        else:
            await self.send_private_info(client_id, "参加者のみアンサーできます。")
            return

        if game.get("current_turn_team") != team:
            await self.send_private_info(client_id, "自分のターンでのみアンサーできます。")
            return

        team_state_key = "team_left" if team == "team-left" else "team_right"
        team_state = game.get(team_state_key, {})
        total_actions = team_state.get("action_points", 0) + team_state.get("bonus_action_points", 0)
        if total_actions <= 0:
            await self.send_private_info(client_id, "アクション権がありません。")
            return

        text = str(answer_text or "").strip()
        if text == "":
            await self.send_private_info(client_id, "解答を入力してください。")
            return

        if len(text) > self.ANSWER_MAX_LENGTH:
            await self.send_private_info(
                client_id,
                f"解答は{self.ANSWER_MAX_LENGTH}文字以内で入力してください。",
            )
            return

        nickname = self.nicknames.get(client_id, "ゲスト")
        voter_ids = self._get_team_participant_ids(room, team)
        if not voter_ids:
            await self.send_private_info(client_id, "投票対象の陣営参加者がいません。")
            return

        total_voters = len(voter_ids)

        if total_voters == 1:
            answer_log_marker_id = str(uuid.uuid4())
            game["pending_answer_judgement"] = {
                "team": team,
                "answer_text": text,
                "answerer_id": client_id,
                "answer_log_marker_id": answer_log_marker_id,
            }
            self._append_kifu_action(
                owner_id,
                "answer",
                team,
                client_id,
                {
                    "answer_text": text,
                    "proposed_by_vote": False,
                },
            )

            if not room.get("is_ai_mode"):
                await self.broadcast_state(
                    public_info=f"{team_label}がアンサーしました。出題者が正誤判定中です。",
                    event_type="answer_attempt",
                    event_room_id=owner_id,
                    event_payload={
                        "team": team,
                        "log_marker_id": answer_log_marker_id,
                    },
                )
            await self._broadcast_team_log_message(
                owner_id,
                room,
                "answer_attempt",
                self._format_answer_attempt_message(team_label, text),
                event_payload={
                    "team": team,
                    "log_marker_id": answer_log_marker_id,
                },
            )

            if room.get("is_ai_mode"):
                await self.send_private_info(client_id, "解答を送信しました。")
                await self._resolve_ai_answer_judgement(owner_id, room, team, text)
                return

            await self.broadcast_state(
                public_info="",
                event_type="answer_judgement_request",
                event_room_id=owner_id,
                event_recipient_ids={owner_id},
                event_payload={
                    "team": team,
                    "team_label": team_label,
                    "answer_text": text,
                    "answerer_name": nickname,
                },
            )
            await self.send_private_info(client_id, "解答を送信しました。")
            return

        should_emit_vote_log = total_voters > 1
        vote_id = str(uuid.uuid4())
        required_approvals = total_voters
        approved_ids = {client_id}
        room["pending_answer_vote"] = {
            "vote_id": vote_id,
            "requester_id": client_id,
            "team": team,
            "answer_text": text,
            "voter_ids": voter_ids,
            "approved_ids": approved_ids,
            "rejected_ids": set(),
            "required_approvals": required_approvals,
            "status": "pending",
        }

        event_recipient_ids = voter_ids - {client_id}

        await self.broadcast_state(
            public_info="",
            event_type="answer_vote_request",
            event_message="",
            event_chat_type=team,
            event_room_id=owner_id,
            event_recipient_ids=event_recipient_ids,
            event_payload={
                "vote_id": vote_id,
                "team": team,
                "team_label": team_label,
                "answer_text": text,
                "answerer_name": nickname,
                "required_approvals": required_approvals,
                "total_voters": total_voters,
                "log_marker_id": vote_id,
            },
        )

        await self.send_private_info(client_id, "提案しました。")

    async def judge_answer(self, client_id: str, payload: JudgeAnswerMessage | bool):
        message = payload if isinstance(payload, JudgeAnswerMessage) else JudgeAnswerMessage(type="judge_answer", is_correct=payload)
        return await judge_answer_handler(self, client_id, message)

    async def _judge_answer_impl(self, client_id: str, is_correct: bool):
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        if ctx["role"] != "owner":
            await self.send_private_info(client_id, "正誤判定は出題者のみ実行できます。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        game = room.get("game") or {}
        pending = game.get("pending_answer_judgement")
        if not pending:
            await self.send_private_info(client_id, "判定待ちの解答がありません。")
            return

        team = pending.get("team")
        answer_text = str(pending.get("answer_text", "")).strip()
        result = await self._finalize_answer_judgement(owner_id, room, team, answer_text, bool(is_correct))
        if not result.get("ok"):
            await self.send_private_info(client_id, result.get("error", "正誤判定に失敗しました。"))

    async def judge_full_open_settlement(
        self,
        client_id: str,
        payload: FullOpenSettlementJudgeMessage | str,
        left_is_correct: bool | None = None,
        right_is_correct: bool | None = None,
    ):
        if isinstance(payload, FullOpenSettlementJudgeMessage):
            message = payload
        else:
            normalized_left_is_correct = left_is_correct if left_is_correct is not None else False
            normalized_right_is_correct = right_is_correct if right_is_correct is not None else False
            message = FullOpenSettlementJudgeMessage(
                type="full_open_settlement_judge",
                vote_id=str(payload or "").strip(),
                left_is_correct=normalized_left_is_correct,
                right_is_correct=normalized_right_is_correct,
            )
        return await judge_full_open_settlement_handler(self, client_id, message)

    async def _judge_full_open_settlement_impl(self, client_id: str, vote_id: str, left_is_correct: bool, right_is_correct: bool):
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            owned_room = self.rooms.get(client_id)
            if isinstance(owned_room, dict) and bool(owned_room.get("is_ai_mode")):
                ctx = {
                    "room_owner_id": client_id,
                    "room": owned_room,
                    "role": "owner",
                    "chat_role": "questioner",
                }
        elif (
            ctx.get("role") != "owner"
            and str(ctx.get("room_owner_id") or "") == str(client_id or "")
            and bool((ctx.get("room") or {}).get("is_ai_mode"))
        ):
            ctx = {
                **ctx,
                "role": "owner",
                "chat_role": "questioner",
            }

        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        if ctx["role"] != "owner":
            await self.send_private_info(client_id, "判定確定は出題者のみ実行できます。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        game = room.get("game") or {}
        full_open = self._get_full_open_settlement_state(room)
        if not isinstance(full_open, dict):
            await self.send_private_info(client_id, "フルオープン決着の進行状態が見つかりません。")
            return

        if str(full_open.get("state") or "") != "judging":
            await self.send_private_info(client_id, "現在は判定確定できる状態ではありません。")
            return

        active_vote_id = str(full_open.get("vote_id") or "")
        if vote_id and active_vote_id and vote_id != active_vote_id:
            await self.send_private_info(client_id, "投票IDが一致しません。")
            return

        answers = dict(full_open.get("answers") or {})
        if str(answers.get("team-left") or "").strip() == "" or str(answers.get("team-right") or "").strip() == "":
            await self.send_private_info(client_id, "両陣営の回答が揃っていません。")
            return

        left_correct = bool(left_is_correct)
        right_correct = bool(right_is_correct)

        if left_correct == right_correct:
            winner = "draw"
        elif left_correct:
            winner = "team-left"
        else:
            winner = "team-right"

        full_open["judgements"] = {
            "team-left": left_correct,
            "team-right": right_correct,
        }
        full_open["final_winner"] = winner
        full_open["state"] = "finished"

        game["winner"] = winner
        game["game_status"] = "finished"
        game["left_correct_waiting"] = False
        game["pending_answer_judgement"] = None
        room["game_state"] = "finished"
        room["pending_open_vote"] = None
        room["pending_answer_vote"] = None
        room["pending_turn_end_vote"] = None
        room["pending_intentional_draw_vote"] = None

        recipients = self._room_member_ids(owner_id, room)
        marker_id = active_vote_id or str(uuid.uuid4())
        finished_marker_id = f"{marker_id}:finished"

        self._append_kifu_action(
            owner_id,
            "intentional_draw",
            "game-global",
            client_id,
            {
                "full_open_settlement": True,
                "vote_id": active_vote_id,
                "left_is_correct": left_correct,
                "right_is_correct": right_correct,
                "winner": winner,
            },
        )

        await self.broadcast_state(
            public_info="フルオープン決着の判定が確定しました。",
            event_type="full_open_settlement_finished",
            event_message=(f"フルオープン決着の判定が確定しました。" f"先攻: {'正解' if left_correct else '誤答'} / " f"後攻: {'正解' if right_correct else '誤答'}"),
            event_chat_type="game-global",
            event_room_id=owner_id,
            event_recipient_ids=recipients,
            event_payload={
                "vote_id": active_vote_id,
                "left_is_correct": left_correct,
                "right_is_correct": right_correct,
                "winner": winner,
                "log_marker_id": finished_marker_id,
                "event_id": finished_marker_id,
            },
        )

        game_finished_message = self._format_game_finished_message(winner)
        await self._broadcast_game_finished_message(owner_id, room, game_finished_message)
        self._finalize_kifu_if_tracking(owner_id, room, "intentional_draw")

    async def connect(self, websocket: WebSocket, client_id: str, nickname: str, user_id: str, session_id: str):
        # 同一 client_id の二重接続は許可しない（別タブ重複やなりすまし抑止）。
        if client_id in self.active_connections:
            await websocket.close(code=1008, reason="Duplicate session")
            print(f"接続拒否（重複client_id）: {client_id}")
            return False

        if session_id in self.active_session_connections:
            await websocket.close(code=1008, reason="Duplicate session")
            print(f"接続拒否（重複session_id）: {session_id}")
            return False

        # 接続上限に達している場合は、即座に通信を切断する
        if len(self.active_connections) >= self.MAX_CONNECTIONS:
            # WebSocketのステータスコード1008は「ポリシー違反（リソース超過など）」を意味します
            await websocket.close(code=1008, reason="Server is full or Rate limited")
            print(f"接続拒否（満員）: {client_id}")
            return False

        await websocket.accept()

        self.active_connections[client_id] = websocket
        self.active_session_connections[session_id] = client_id
        self.nicknames[client_id] = nickname
        self.client_user_ids[client_id] = str(user_id or "")
        self.client_session_ids[client_id] = str(session_id or "")
        restored = self._try_restore_participant_reconnect(client_id)
        self._clear_pending_disconnect_everywhere(client_id)
        self._cancel_disconnect_grace_timer(client_id)
        print(f"プレイヤー接続: {nickname} ({client_id}) (現在: {len(self.active_connections)}人)")

        await self.broadcast_state(
            public_info=f"{nickname} が参加しました",
            private_map={client_id: "QuizOpenBattleへようこそ"},
            event_type="join",
            event_message=f"{nickname} が入場しました",
            event_chat_type="lobby",
        )

        if restored:
            restored_room_owner_id = restored.get("room_owner_id")
            restored_kind = str(restored.get("kind") or "participant")
            if restored_kind == "participant":
                await self.send_private_info(
                    client_id,
                    "再接続して部屋に復帰しました。",
                    target_screen="game_arena",
                    event_type="room_reconnected",
                )
                if isinstance(restored_room_owner_id, str) and restored_room_owner_id != "":
                    await self._resend_pending_votes_to_client(restored_room_owner_id, client_id)
            else:
                restored_room = self.rooms.get(restored_room_owner_id)
                should_open_arena = isinstance(restored_room, dict) and not bool(restored_room.get("is_ai_mode"))
                await self.send_private_info(
                    client_id,
                    "対戦中の出題部屋が維持されています。",
                    target_screen="game_arena" if should_open_arena else None,
                    event_type="room_reconnected",
                )
                if isinstance(restored_room_owner_id, str) and restored_room_owner_id != "":
                    await self._resend_pending_answer_judgement_to_client(restored_room_owner_id, client_id)
        return True

    async def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            ctx_before_disconnect = resolve_client_room_context(self.rooms, client_id)
            owned_room_before_disconnect = self.rooms.get(client_id)
            reservation = self._reserve_participant_reconnect(client_id, ctx_before_disconnect)

            del self.active_connections[client_id]
            session_id = self.client_session_ids.pop(client_id, "")
            if session_id != "":
                self.active_session_connections.pop(session_id, None)
            self.client_user_ids.pop(client_id, None)
            nickname = self.nicknames.pop(client_id, client_id)
            self.chat_message_history.pop(client_id, None)
            self.chat_last_message.pop(client_id, None)

            closed_room = None
            reservation_kind = str((reservation or {}).get("kind") or "")
            should_close_owned_room = owned_room_before_disconnect is not None
            if owned_room_before_disconnect is not None:
                owned_room_game_state = str(owned_room_before_disconnect.get("game_state") or "waiting")
                owned_room_is_ai = bool(owned_room_before_disconnect.get("is_ai_mode"))
                owner_joined_as_guest = self._is_owner_joined_as_guest(client_id, owned_room_before_disconnect)

                if reservation_kind == "owner":
                    should_close_owned_room = False
                elif owned_room_is_ai and owner_joined_as_guest:
                    should_close_owned_room = False
                elif owned_room_is_ai and not owner_joined_as_guest and owned_room_game_state == "playing":
                    should_close_owned_room = False

            if should_close_owned_room and owned_room_before_disconnect is not None:
                closed_room = self.rooms.pop(client_id, None)

            is_participant_grace_disconnect = reservation_kind == "participant" and closed_room is None
            if not is_participant_grace_disconnect:
                remove_client_from_all_rooms_logic(self.rooms, client_id)

            if is_participant_grace_disconnect and reservation is not None:
                room_owner_id = reservation.get("room_owner_id")
                team = reservation.get("team")
                expires_at = float(reservation.get("expires_at") or 0)
                if room_owner_id and team in {"team-left", "team-right"} and expires_at > time.time():
                    self._set_room_pending_disconnect(room_owner_id, client_id, nickname, team, expires_at)
                    self._schedule_participant_disconnect_grace(client_id, room_owner_id, expires_at, nickname)

                    remaining_seconds = max(1, int(expires_at - time.time()))
                    team_label = self._team_label(team)
                    await self.broadcast_state(
                        public_info=f"{nickname} が切断されました。再接続を待っています。",
                        event_type="participant_timeout_pending",
                        event_message=f"{team_label}の {nickname} が接続タイムアウト中です。",
                        event_room_id=room_owner_id,
                        event_payload={
                            "client_id": client_id,
                            "nickname": nickname,
                            "team": team,
                            "expires_at": expires_at,
                            "remaining_seconds": remaining_seconds,
                        },
                    )

            if reservation_kind == "owner" and reservation is not None:
                room_owner_id = reservation.get("room_owner_id")
                if room_owner_id in self.rooms:
                    await self.broadcast_state(
                        public_info=f"{nickname} が切断されました。復帰を待機しています。",
                        event_type="owner_reconnect_pending",
                        event_message=f"出題者の {nickname} が一時的に切断されました。",
                        event_room_id=room_owner_id,
                        event_payload={
                            "client_id": client_id,
                            "nickname": nickname,
                            "room_owner_id": room_owner_id,
                            "indefinite": True,
                        },
                    )

            if closed_room is not None:
                self._finalize_kifu_if_tracking(client_id, closed_room, "owner_disconnected")
                self._clear_room_reconnect_reservations(client_id)
                affected_client_ids = set(closed_room["left_participants"]) | set(closed_room["right_participants"]) | set(closed_room["spectators"])
                for target_client_id in affected_client_ids:
                    await self.send_private_info(
                        target_client_id,
                        "出題者が退室したため、部屋から退室しました。",
                        target_screen="waiting_room",
                        event_type="forced_exit_notice",
                    )

            print(f"プレイヤー切断: {nickname} ({client_id}) (現在: {len(self.active_connections)}人)")
            await self.broadcast_state(
                public_info=f"{nickname} が退室しました",
                event_type="leave",
                event_message=f"{nickname} が退場しました",
                event_chat_type="lobby",
            )

            if closed_room is not None:
                await self.broadcast_state(
                    public_info=f"{nickname} の部屋が閉じられました",
                    event_type="room_closed",
                    event_message=f"{nickname} の出題部屋が閉じられました",
                    event_room_id=client_id,
                )

    async def exit_room(self, client_id: str, payload: RoomExitMessage | None = None):
        ctx_before_exit = resolve_client_room_context(self.rooms, client_id)
        room_owner_id_before_exit = ctx_before_exit.get("room_owner_id") if ctx_before_exit else None
        room_before_exit = ctx_before_exit.get("room") if isinstance(ctx_before_exit, dict) else None
        user_id_before_exit = str(self.client_user_ids.get(client_id) or "").strip()
        if isinstance(ctx_before_exit, dict):
            self._mark_forced_loss_user_id(
                room_before_exit,
                user_id_before_exit,
                ctx_before_exit.get("chat_role"),
            )

        self._cancel_disconnect_grace_timer(client_id)
        self._clear_pending_disconnect_everywhere(client_id)
        self.reconnect_reservations.pop(client_id, None)
        nickname = self.nicknames.get(client_id, "ゲスト")

        result = apply_exit_room(self.rooms, client_id)
        if result.get("owner_closed"):
            closed_room_snapshot = ctx_before_exit.get("room") if isinstance(ctx_before_exit, dict) else None
            self._finalize_kifu_if_tracking(client_id, closed_room_snapshot, "owner_closed")
            for target_client_id in result.get("affected_client_ids", set()):
                await self.send_private_info(
                    target_client_id,
                    "出題者が退室したため、部屋から退室しました。",
                    target_screen="waiting_room",
                    event_type="forced_exit_notice",
                )

            await self.broadcast_state(
                public_info=f"{nickname} が出題部屋を閉じました",
                event_type="room_closed",
                event_message=f"{nickname} の出題部屋が閉じられました",
                event_room_id=client_id,
            )
            return

        await self.broadcast_state(
            public_info=f"{nickname} が部屋から退室しました",
            event_type="room_exit",
            event_message=f"{nickname} が部屋から退室しました",
            event_room_id=room_owner_id_before_exit,
        )

        if room_owner_id_before_exit is not None:
            room = self.rooms.get(room_owner_id_before_exit)
            if room is not None:
                await self._evaluate_team_forfeit_if_needed(room_owner_id_before_exit, room)

    async def process_question(self, player_id: str, payload: QuestionSubmissionMessage | dict[str, Any]):
        message = payload if isinstance(payload, QuestionSubmissionMessage) else validate_message(QuestionSubmissionMessage, payload)
        return await process_question_handler(self, player_id, message)

    async def _process_question_impl(self, player_id: str, payload: QuestionSubmissionMessage):
        normalized_payload = dump_message(payload)
        is_ai_mode = bool(normalized_payload.get("is_ai_mode"))
        model_id = normalize_model_id(normalized_payload.get("model_id"))
        requester_name = self.nicknames.get(player_id, "ゲスト")

        if self.is_guest_client(player_id):
            await self.send_private_info(player_id, "ゲスト参加中は出題できません。ログイン後に利用してください。")
            return

        if is_ai_mode:
            async with self.ai_question_generation_lock:
                if self.ai_question_generation_active:
                    await self.send_private_info(player_id, "他のAI問題を生成中です。しばらく待ってから再試行してください。")
                    return

                if self._has_active_ai_room():
                    await self.send_private_info(player_id, "すでにAI出題部屋があるため、AI出題はできません。")
                    return

                self.ai_question_generation_active = True
                self.ai_question_generation_owner_id = player_id

            await self.broadcast_state(
                public_info="",
                event_type="ai_generation_state",
                event_room_id=player_id,
                event_payload={
                    "active": True,
                    "owner_id": player_id,
                },
            )
            await self.broadcast_state(
                public_info="",
                event_type="chat",
                event_message=f"{requester_name}がAI出題をリクエストしました",
                event_chat_type="lobby",
            )

            quiz_data = None
            genre = str(normalized_payload.get("genre", "")).strip() or "一般常識"
            difficulty = normalize_difficulty(normalized_payload.get("accuracy_rate", normalized_payload.get("difficulty", None)))
            generation_timeout = 100.0
            try:
                try:
                    quiz_generation_result = generate_quiz_async(genre, model_id=model_id, difficulty=difficulty)
                    if asyncio.iscoroutine(quiz_generation_result):
                        quiz_data = await asyncio.wait_for(quiz_generation_result, timeout=generation_timeout)
                    else:
                        quiz_data = quiz_generation_result
                except asyncio.TimeoutError as e:
                    print(
                        "AI問題生成タイムアウト:",
                        {
                            "model_id": model_id,
                            "genre": genre,
                            "difficulty": difficulty,
                            "timeout": generation_timeout,
                            "error": repr(e),
                        },
                    )
                    await self.send_private_info(player_id, "AI問題の生成がタイムアウトしました。時間をおいて再試行してください。")
                    await self.broadcast_state(
                        public_info="",
                        event_type="chat",
                        event_message=f"{requester_name}のAI出題は失敗しました",
                        event_chat_type="lobby",
                    )
                    return
                except Exception as e:
                    print(
                        "AI問題生成失敗:",
                        {
                            "model_id": model_id,
                            "genre": genre,
                            "difficulty": difficulty,
                            "error": repr(e),
                        },
                    )
                    await self.send_private_info(player_id, "AI問題の生成に失敗しました。時間をおいて再試行してください。")
                    await self.broadcast_state(
                        public_info="",
                        event_type="chat",
                        event_message=f"{requester_name}のAI出題は失敗しました",
                        event_chat_type="lobby",
                    )
                    return

                quiz_payload = quiz_data if isinstance(quiz_data, dict) else {}
                question_text = str(quiz_payload.get("question", "")).strip()
                expected_answer = str(quiz_payload.get("answer", "")).strip()
                error_code = str(quiz_payload.get("error_code", "")).strip()
                if error_code == "RESOURCE_EXHAUSTED":
                    await self.send_private_info(
                        player_id,
                        "AI APIの利用上限に達しているため問題生成できません。\n課金上限または請求設定を確認してください。",
                    )
                    await self.broadcast_state(
                        public_info="",
                        event_type="chat",
                        event_message=f"{requester_name}のAI出題は失敗しました",
                        event_chat_type="lobby",
                    )
                    return

                if question_text == "" or expected_answer == "" or expected_answer == "エラー":
                    print(
                        "AI問題生成結果が不正:",
                        {
                            "model_id": model_id,
                            "genre": genre,
                            "difficulty": difficulty,
                            "question_text": question_text,
                            "expected_answer": expected_answer,
                        },
                    )
                    await self.send_private_info(player_id, "AI問題の生成に失敗しました。時間をおいて再試行してください。")
                    await self.broadcast_state(
                        public_info="",
                        event_type="chat",
                        event_message=f"{requester_name}のAI出題は失敗しました",
                        event_chat_type="lobby",
                    )
                    return

                normalized_payload["question_text"] = question_text
                normalized_payload["questioner_name"] = "AI"
                normalized_payload["questioner_id"] = "ai-questioner"
                normalized_payload["genre"] = genre
                normalized_payload["difficulty"] = difficulty
                normalized_payload["accuracy_rate"] = difficulty
                normalized_payload["model_id"] = model_id

                result = apply_create_question_room(self.rooms, self.nicknames, player_id, normalized_payload)
                if not result.get("ok"):
                    await self.send_private_info(player_id, result.get("error", "出題に失敗しました。"))
                    await self.broadcast_state(
                        public_info="",
                        event_type="chat",
                        event_message=f"{requester_name}のAI出題は失敗しました",
                        event_chat_type="lobby",
                    )
                    return

                room = self.rooms.get(player_id)
                if room is not None:
                    room["is_ai_mode"] = True
                    room["ai_genre"] = str(normalized_payload.get("genre", "")).strip() or "一般常識"
                    room["ai_difficulty"] = difficulty
                    room["ai_expected_answer"] = str(quiz_payload.get("answer", "")).strip()
                    room["ai_expected_answer_revealed"] = False
                    room["ai_model_id"] = model_id

                await self.broadcast_state(
                    public_info="",
                    event_type="chat",
                    event_message=f"{requester_name}がAI問題を作成しました。",
                    event_chat_type="lobby",
                )
            finally:
                async with self.ai_question_generation_lock:
                    if self.ai_question_generation_owner_id == player_id:
                        self.ai_question_generation_active = False
                        self.ai_question_generation_owner_id = None

                await self.broadcast_state(
                    public_info="",
                    event_type="ai_generation_state",
                    event_room_id=player_id,
                    event_payload={
                        "active": False,
                        "owner_id": None,
                    },
                )

            return

        result = apply_create_question_room(self.rooms, self.nicknames, player_id, normalized_payload)
        if not result.get("ok"):
            await self.send_private_info(player_id, result.get("error", "出題に失敗しました。"))
            return

        private_map = {}
        actor_name = result["actor_name"]

        for client_id in self.active_connections.keys():
            if client_id == player_id:
                private_map[client_id] = "あなたは問題を出題しました。"
            else:
                private_map[client_id] = f"{actor_name} が行動を完了しました。あなたのターンです。"

        await self.broadcast_state(
            public_info="行動が受理されました",
            private_map=private_map,
            event_type="question",
            event_message=f"{actor_name} が出題をしました",
            event_room_id=player_id,
        )

        # AI出題では作成者を強制入室させない。必要なら room_entry で参加/観戦する。
        if not is_ai_mode:
            await self.send_private_info(player_id, "", target_screen="game_arena")

    async def process_chat_message(self, client_id: str, payload: ChatMessage | dict[str, Any]):
        message = payload if isinstance(payload, ChatMessage) else validate_message(ChatMessage, payload)
        return await process_chat_message_handler(self, client_id, message)

    async def _process_chat_message_impl(self, client_id: str, payload: ChatMessage):
        message = str(payload.message).replace("\r\n", "\n").replace("\r", "\n").strip()
        if message == "":
            return

        chat_type = str(payload.chat_type).strip() or "lobby"

        if len(message) > self.CHAT_MAX_LENGTH:
            await self.send_private_info(
                client_id,
                f"チャットは{self.CHAT_MAX_LENGTH}文字以内で送信してください。",
            )
            return

        now = time.time()
        history = self.chat_message_history.setdefault(client_id, [])
        valid_since = now - self.CHAT_RATE_WINDOW_SECONDS
        history[:] = [sent_at for sent_at in history if sent_at >= valid_since]

        if history and now - history[-1] < self.CHAT_MIN_INTERVAL_SECONDS:
            wait_seconds = self.CHAT_MIN_INTERVAL_SECONDS - (now - history[-1])
            await self.send_private_info(
                client_id,
                f"連続投稿が早すぎます。{wait_seconds:.1f}秒待ってください。",
            )
            return

        if len(history) >= self.CHAT_RATE_WINDOW_MAX_MESSAGES:
            await self.send_private_info(
                client_id,
                f"短時間での投稿が多すぎます。{int(self.CHAT_RATE_WINDOW_SECONDS)}秒後に再試行してください。",
            )
            return

        last_chat = self.chat_last_message.get(client_id)
        if last_chat is not None:
            last_message_text, last_message_at = last_chat
            if message == last_message_text and now - last_message_at < 6.0:
                await self.send_private_info(client_id, "同じ内容の連投は少し時間を空けてください。")
                return

        nickname = self.nicknames.get(client_id, "ゲスト")

        if chat_type == "lobby":
            history.append(now)
            self.chat_last_message[client_id] = (message, now)
            await self.broadcast_state(
                public_info=f"{nickname} がチャットを送信しました",
                event_type="chat",
                event_message=f"{nickname}: {message}",
                event_chat_type="lobby",
            )
            return

        room_ctx = resolve_client_room_context(self.rooms, client_id)
        if room_ctx is None:
            await self.send_private_info(client_id, "部屋に参加していないため、部屋内チャットは送信できません。")
            return

        room_owner_id = room_ctx["room_owner_id"]
        room = room_ctx["room"]
        sender_chat_role = room_ctx["chat_role"]

        if chat_type == "game-global" and room.get("game_state", "waiting") == "waiting":
            pre_seq = int(room.get("pre_game_global_chat_seq", 0)) + 1
            room["pre_game_global_chat_seq"] = pre_seq
            pre_timestamp = int(time.time() * 1000)
            pre_event_id = f"{room_owner_id}:pre:{pre_seq}"
            pre_history = room.setdefault("pre_game_global_chat_history", [])
            if not isinstance(pre_history, list):
                pre_history = []
                room["pre_game_global_chat_history"] = pre_history
            pre_history.append(
                {
                    "seq": pre_seq,
                    "timestamp": pre_timestamp,
                    "event_type": "chat",
                    "event_message": f"{nickname}: {message}",
                    "event_chat_type": "game-global",
                    "event_id": pre_event_id,
                    "event_revision": 1,
                    "event_version": pre_seq,
                }
            )
            while len(pre_history) > 200:
                pre_history.pop(0)

        chat_result = resolve_chat_recipients(room_owner_id, room, sender_chat_role, chat_type)
        if not chat_result.get("ok"):
            await self.send_private_info(client_id, chat_result.get("error", "チャット送信に失敗しました。"))
            return

        event_recipient_ids = chat_result["event_recipient_ids"]

        history.append(now)
        self.chat_last_message[client_id] = (message, now)
        await self.broadcast_state(
            public_info=f"{nickname} がチャットを送信しました",
            event_type="chat",
            event_message=f"{nickname}: {message}",
            event_chat_type=chat_type,
            event_room_id=room_owner_id,
            event_recipient_ids=event_recipient_ids,
        )

    async def process_client_payload(self, client_id: str, payload: dict):
        if not isinstance(payload, dict):
            print(f"警告: {client_id} から辞書以外のペイロードを受信しました: {type(payload).__name__}")
            await self.send_private_info(client_id, "メッセージ形式が不正です。")
            return

        normalized_payload = dict(payload)
        payload_type = str(normalized_payload.get("type") or normalized_payload.get("action") or "").strip()
        if payload_type != "":
            normalized_payload["type"] = payload_type

        route = MESSAGE_ROUTER.get(payload_type)
        if route is not None:
            try:
                message = validate_message(route.model, normalized_payload)
            except ValidationError as exc:
                print(
                    "WebSocketメッセージ検証エラー:",
                    {
                        "client_id": client_id,
                        "type": payload_type,
                        "errors": exc.errors(),
                    },
                )
                await self.send_private_info(client_id, "メッセージ形式が不正です。")
                return

            handler = getattr(self, route.handler_name)
            await handler(client_id, message)
            return

        # 旧フォーマット互換: typeなしでも問題送信として扱う。
        if payload_type == "" and ("question_text" in normalized_payload or "content" in normalized_payload):
            try:
                message = validate_message(LegacyQuestionSubmissionMessage, normalized_payload)
            except ValidationError as exc:
                print(
                    "WebSocketメッセージ検証エラー:",
                    {
                        "client_id": client_id,
                        "type": "question_submission",
                        "errors": exc.errors(),
                    },
                )
                await self.send_private_info(client_id, "メッセージ形式が不正です。")
                return

            await self.process_question(client_id, message)
            return

        print(
            "未対応のWebSocketメッセージを受信しました:",
            {
                "client_id": client_id,
                "type": payload_type,
                "keys": sorted(normalized_payload.keys()),
            },
        )
        await self.send_private_info(client_id, "未対応のメッセージ形式です。")


manager = QuizGameManager()
ws_auth_manager = WebSocketAuthManager()
account_auth_manager = AccountAuthManager()
manager.account_auth_manager = account_auth_manager

register_api_routes(app, manager, ws_auth_manager, account_auth_manager, diag_api_log)


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    client_id = str(client_id or "").strip()
    ws_ticket = str(websocket.query_params.get("ws_ticket", "")).strip()

    if not is_valid_client_id(client_id):
        await websocket.close(code=1008, reason="Invalid client id")
        return

    is_valid_ticket, reason, ticket_payload = ws_auth_manager.verify_ticket(ws_ticket, client_id)
    if not is_valid_ticket:
        await websocket.close(code=1008, reason=f"Unauthorized: {reason}")
        return

    session_id = str(ticket_payload.get("session_id") or "").strip()
    is_guest = bool(ticket_payload.get("is_guest"))
    user_id = str(ticket_payload.get("user_id") or "").strip()
    if not is_guest:
        session = account_auth_manager.store.get_session(session_id, touch=True)
        if session is None:
            await websocket.close(code=1008, reason="Unauthorized: session_expired")
            return

        if user_id == "" or str(session.get("user_id") or "") != user_id:
            await websocket.close(code=1008, reason="Unauthorized: session_mismatch")
            return

        if not account_auth_manager.can_user_access_client_id(user_id, client_id):
            await websocket.close(code=1008, reason="Unauthorized: client_mismatch")
            return

    raw_nickname = ticket_payload.get("nickname")
    nickname = sanitize_nickname(raw_nickname if isinstance(raw_nickname, str) else "ゲスト")

    # 接続処理を行い、許可されなかった（False）場合はここで処理を終える
    is_accepted = await manager.connect(websocket, client_id, nickname, user_id, session_id)
    if not is_accepted:
        return

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                await manager.process_client_payload(client_id, payload)

            except json.JSONDecodeError:
                # 不正な文字列スパムが送られてきた場合、エラーでサーバーを落とさずに「無視」する
                print(f"警告: {client_id} から不正なデータを受信しました")
                pass

    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as exc:
        print(f"WebSocket処理中に予期せぬ例外が発生: {client_id} ({exc})")
        await manager.disconnect(client_id)

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid

from pydantic import BaseModel

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
from backend.model_catalog import get_frontend_model_payload
from backend.kifu_storage import (
    append_action,
    begin_kifu_record,
    finalize_kifu_record,
    get_kifu_detail_for_client,
    list_kifu_for_client,
    resolve_latest_answer_result,
    touch_spectator,
)

app = FastAPI()

app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")


CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
MAX_NICKNAME_LENGTH = 24
QUIZ_DIAG_API_ENABLED = os.getenv("QUIZ_DIAG_API", "").strip() == "1"


def diag_api_log(event: str, **fields):
    if not QUIZ_DIAG_API_ENABLED:
        return

    safe_fields = {str(k): v for k, v in fields.items()}
    print(f"[quiz-diag-api] {event} {json.dumps(safe_fields, ensure_ascii=False)}")


def sanitize_nickname(raw_value: str | None) -> str:
    nickname = str(raw_value or "").strip()
    if nickname == "":
        return "ゲスト"
    return nickname[:MAX_NICKNAME_LENGTH]


def is_valid_client_id(client_id: str) -> bool:
    return bool(CLIENT_ID_PATTERN.fullmatch(str(client_id or "").strip()))


class WsTicketIssueRequest(BaseModel):
    client_id: str
    nickname: str


class WebSocketAuthManager:
    def __init__(self):
        secret_text = os.getenv("QUIZ_WS_AUTH_SECRET", "").strip()
        if secret_text:
            self._secret = secret_text.encode("utf-8")
        else:
            self._secret = secrets.token_bytes(32)
            print("警告: QUIZ_WS_AUTH_SECRET 未設定のため、再起動ごとに WebSocket 認証鍵が再生成されます。")

        self.ticket_ttl_seconds = 45
        self.used_ticket_nonces = {}

    def _purge_expired_nonces(self):
        now = int(time.time())
        for nonce, exp in list(self.used_ticket_nonces.items()):
            if exp <= now:
                self.used_ticket_nonces.pop(nonce, None)

    def _sign(self, payload_segment: str) -> str:
        signature = hmac.new(self._secret, payload_segment.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")

    def _decode_base64url(self, value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)

    def issue_ticket(self, client_id: str, nickname: str) -> dict:
        now = int(time.time())
        expires_at = now + self.ticket_ttl_seconds
        nonce = secrets.token_urlsafe(18)

        payload = {
            "cid": client_id,
            "nick": nickname,
            "exp": expires_at,
            "nonce": nonce,
        }
        payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        payload_segment = base64.urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")
        signature_segment = self._sign(payload_segment)

        return {
            "ticket": f"{payload_segment}.{signature_segment}",
            "expires_at": expires_at,
        }

    def verify_ticket(self, token: str, client_id: str, nickname: str) -> tuple[bool, str]:
        self._purge_expired_nonces()

        token_text = str(token or "").strip()
        if token_text.count(".") != 1:
            return False, "invalid_format"

        payload_segment, signature_segment = token_text.split(".", 1)
        expected_signature = self._sign(payload_segment)
        if not hmac.compare_digest(signature_segment, expected_signature):
            return False, "invalid_signature"

        try:
            payload_raw = self._decode_base64url(payload_segment)
            payload = json.loads(payload_raw.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return False, "invalid_payload"

        token_client_id = str(payload.get("cid", "")).strip()
        token_nickname = sanitize_nickname(payload.get("nick", ""))
        expires_at = int(payload.get("exp", 0))
        nonce = str(payload.get("nonce", "")).strip()

        if token_client_id != client_id:
            return False, "client_mismatch"
        if token_nickname != nickname:
            return False, "nickname_mismatch"
        if expires_at <= int(time.time()):
            return False, "expired"
        if nonce == "":
            return False, "invalid_nonce"
        if nonce in self.used_ticket_nonces:
            return False, "reused_ticket"

        self.used_ticket_nonces[nonce] = expires_at
        return True, "ok"


class QuizGameManager:
    def __init__(self):
        self.active_connections = {}
        self.nicknames = {}
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

    def _has_active_ai_room(self):
        return any(bool(room.get("is_ai_mode")) for room in self.rooms.values())

    def _start_kifu_tracking(self, room_owner_id: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            return

        kifu_id = begin_kifu_record(room_owner_id, room, self.nicknames)
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

        touch_spectator(kifu_id, client_id, self.nicknames.get(client_id, "ゲスト"))

    def _resolve_kifu_latest_answer(self, room_owner_id: str, team: str, answer_text: str, is_correct: bool):
        kifu_id = self.active_kifu_by_room_owner.get(room_owner_id)
        if not kifu_id:
            return

        resolve_latest_answer_result(kifu_id, team, answer_text, is_correct)

    def _finalize_kifu_if_tracking(self, room_owner_id: str, room: dict | None, finish_reason: str):
        kifu_id = self.active_kifu_by_room_owner.pop(room_owner_id, None)
        if not kifu_id:
            return

        finalize_kifu_record(kifu_id, room, finish_reason)

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
        payload = event_payload if isinstance(event_payload, dict) else {}
        event_kind = str(event_type or "").strip()
        event_scope = str(event_chat_type or "").strip() or "game-global"

        room_event_version = 1
        room_event_seq = None
        if event_room_id:
            room = self.rooms.get(event_room_id)
            if room is not None:
                room_event_seq = int(room.get("arena_event_id_seq", 0)) + 1
                room["arena_event_id_seq"] = room_event_seq
                room_event_version = room_event_seq

        payload_event_id = str(payload.get("event_id") or "").strip()
        vote_id = str(payload.get("vote_id") or "").strip()
        log_marker_id = str(payload.get("log_marker_id") or "").strip()

        if payload_event_id != "":
            event_id = payload_event_id
        elif vote_id != "":
            event_id = f"vote:{vote_id}"
        elif log_marker_id != "":
            event_id = f"marker:{log_marker_id}"
        elif event_room_id and room_event_seq is not None:
            event_id = f"{event_room_id}:evt:{room_event_seq}"
        elif event_room_id:
            event_id = self._next_room_event_id(event_room_id)
        else:
            event_id = str(uuid.uuid4())

        payload_revision = payload.get("event_revision")
        if isinstance(payload_revision, int) and payload_revision > 0:
            event_revision = payload_revision
        elif vote_id != "":
            event_revision = 2 if event_kind.endswith("_resolved") else 1
        else:
            event_revision = 1

        return {
            "event_id": event_id,
            "event_kind": event_kind,
            "event_scope": event_scope,
            "event_revision": event_revision,
            "event_version": room_event_version,
        }

    def build_participants(self):
        participants = []
        for client_id, nickname in self.nicknames.items():
            participants.append({"client_id": client_id, "nickname": nickname})
        return participants

    def build_rooms_summary(self, viewer_client_id: str | None = None):
        rooms = []
        for owner_id, room in self.rooms.items():
            participant_count = len(room["left_participants"]) + len(room["right_participants"])
            rooms.append(
                {
                    "room_owner_id": owner_id,
                    "room_owner_name": self.nicknames.get(owner_id, "ゲスト"),
                    "questioner_name": room["questioner_name"],
                    "genre": str(room.get("genre") or "").strip(),
                    "is_ai_room": bool(room.get("is_ai_mode")),
                    "participant_count": participant_count,
                    "spectator_count": len(room["spectators"]),
                    "game_state": room.get("game_state", "waiting"),
                    "can_join_as_participant": room.get("game_state", "waiting") == "waiting",
                    "is_owner": viewer_client_id == owner_id,
                }
            )
        return rooms

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
        arena_progress_event_types = {
            "game_start",
            "game_finished",
            "question",
            "room_shuffle",
            "character_opened",
            "answer_submitted",
            "open_vote_request",
            "open_vote_resolved",
            "answer_attempt",
            "answer_result",
            "answer_vote_request",
            "answer_vote_resolved",
            "turn_end_vote_request",
            "turn_end_vote_resolved",
            "intentional_draw_vote_request",
            "intentional_draw_vote_resolved",
            "intentional_draw",
            "turn_changed",
            "room_reconnected",
        }
        history_message = str(event_message or public_info or "").strip()
        payload_event_timestamp = None
        if isinstance(event_payload, dict):
            raw_event_timestamp = event_payload.get("event_timestamp")
            if isinstance(raw_event_timestamp, int) and raw_event_timestamp > 0:
                payload_event_timestamp = raw_event_timestamp
            elif isinstance(raw_event_timestamp, str):
                raw_event_timestamp = raw_event_timestamp.strip()
                if raw_event_timestamp.isdigit():
                    parsed_event_timestamp = int(raw_event_timestamp)
                    if parsed_event_timestamp > 0:
                        payload_event_timestamp = parsed_event_timestamp

        event_timestamp = payload_event_timestamp or int(time.time() * 1000)
        event_identity = self._derive_event_identity(
            event_room_id=event_room_id,
            event_type=event_type,
            event_chat_type=event_chat_type,
            event_payload=event_payload,
        )
        log_marker_id = None
        if isinstance(event_payload, dict):
            payload_marker = event_payload.get("log_marker_id") or event_payload.get("vote_id")
            payload_marker_text = str(payload_marker or "").strip()
            if payload_marker_text != "":
                log_marker_id = payload_marker_text

        skip_history = isinstance(event_payload, dict) and bool(event_payload.get("skip_history"))
        if history_message and not skip_history and self._should_append_lobby_chat_history(event_type, event_chat_type, event_room_id):
            self._append_lobby_chat_history(
                event_type=event_type or "",
                event_message=history_message,
                event_chat_type=str(event_chat_type or "").strip() or "lobby",
                event_identity=event_identity,
                log_marker_id=log_marker_id,
                event_timestamp=event_timestamp,
            )

        if event_room_id and history_message and not skip_history:
            if event_chat_type in {"team-left", "team-right", "game-global"}:
                self._append_arena_chat_history(
                    event_room_id,
                    event_type or "",
                    history_message,
                    event_chat_type,
                    log_marker_id,
                    event_identity=event_identity,
                    event_payload=event_payload,
                    event_timestamp=event_timestamp,
                )
            elif event_type in {"room_entry", "room_exit"}:
                self._append_arena_chat_history(
                    event_room_id,
                    event_type,
                    history_message,
                    "game-global",
                    log_marker_id,
                    event_identity=event_identity,
                    event_payload=event_payload,
                    event_timestamp=event_timestamp,
                )
            elif event_type in arena_progress_event_types:
                self._append_arena_chat_history(
                    event_room_id,
                    event_type or "",
                    history_message,
                    "game-global",
                    log_marker_id,
                    event_identity=event_identity,
                    event_payload=event_payload,
                    event_timestamp=event_timestamp,
                )

        participants = self.build_participants()
        for client_id, ws in self.active_connections.items():
            rooms = self.build_rooms_summary(client_id)
            current_room = self.build_current_room_for_client(client_id)
            private_info = ""
            if private_map is not None:
                private_info = private_map.get(client_id, "")

            is_event_recipient = event_recipient_ids is None or client_id in event_recipient_ids
            response_event_type = event_type if is_event_recipient else None
            response_event_message = (
                self._resolve_event_message_for_client(
                    current_room,
                    event_type,
                    event_chat_type,
                    history_message,
                    event_payload,
                )
                if is_event_recipient
                else None
            )
            response_event_payload = (
                self._resolve_event_payload_for_client(
                    current_room,
                    event_type,
                    event_chat_type,
                    event_payload,
                )
                if is_event_recipient
                else None
            )
            response_event_chat_type = event_chat_type if is_event_recipient else None

            response = {
                "public_info": public_info,
                "private_info": private_info,
                "participants": participants,
                "rooms": rooms,
                "current_room": current_room,
                "lobby_chat_history": self._build_lobby_chat_history_snapshot(),
                "ai_question_generation_active": self.ai_question_generation_active,
                "ai_question_generation_owner_id": self.ai_question_generation_owner_id,
                "event_type": response_event_type,
                "event_message": response_event_message,
                "event_chat_type": response_event_chat_type,
                "event_room_id": event_room_id,
                "target_screen": target_screen,
                "event_payload": response_event_payload,
                "event_view": (
                    {
                        "display_message": response_event_message,
                        "masked": bool(response_event_message is not None and response_event_message != history_message),
                    }
                    if is_event_recipient
                    else None
                ),
                "event_id": event_identity["event_id"] if is_event_recipient else None,
                "event_kind": event_identity["event_kind"] if is_event_recipient else None,
                "event_scope": event_identity["event_scope"] if is_event_recipient else None,
                "event_revision": event_identity["event_revision"] if is_event_recipient else None,
                "event_version": event_identity["event_version"] if is_event_recipient else None,
                "event_timestamp": event_timestamp if is_event_recipient else None,
            }
            await ws.send_text(json.dumps(response))

        should_reveal_finished_answers = event_type == "game_finished" and bool(event_room_id) and not (isinstance(event_payload, dict) and bool(event_payload.get("skip_finished_answer_reveal")))
        if should_reveal_finished_answers:
            await self._rebroadcast_finished_answer_logs(str(event_room_id))

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
        next_label = self._team_label(str(next_turn_team or ""))
        if next_label == "":
            return "ターン終了。"
        return f"ターン終了。{next_label}のターンになりました。"

    def _format_open_vote_request_message(self, requester_name: str, char_index: int, should_emit_vote_log: bool):
        if should_emit_vote_log:
            return f"{requester_name} が {char_index + 1}文字目のオープン投票を開始しました。"
        return f"{requester_name} が {char_index + 1}文字目をオープンしました。"

    def _format_open_vote_resolution_message(self, team_label: str, char_index: int, approved: bool):
        if approved:
            return f"{team_label}が{char_index + 1}文字目をオープンしました。"
        return f"{team_label}が{char_index + 1}文字目をオープンできませんでした。"

    def _format_answer_attempt_message(self, team_label: str, answer_text: str):
        return f"{team_label}が「{answer_text}」とアンサーしました。"

    def _format_answer_vote_request_message(self, requester_name: str, answer_text: str, should_emit_vote_log: bool):
        if should_emit_vote_log:
            return f"{requester_name} が「{answer_text}」とアンサーしました。"
        return f"{requester_name} が「{answer_text}」とアンサーしました。"

    def _format_answer_vote_resolution_message(self, team_label: str, answer_text: str, approved: bool, should_emit_vote_log: bool):
        if approved:
            return f"{team_label}が「{answer_text}」とアンサーしました。"
        if should_emit_vote_log:
            return "アンサー投票否決"
        return f"{team_label}の解答送信に失敗しました。"

    def _format_turn_end_vote_request_message(self, requester_name: str, should_emit_vote_log: bool):
        if should_emit_vote_log:
            return f"{requester_name} がターンエンド投票を開始しました。"
        return f"{requester_name} がターンエンドしました。"

    def _format_turn_end_vote_resolution_message(self, approved: bool):
        return "ターンエンド投票可決" if approved else "ターンエンド投票否決"

    def _format_intentional_draw_vote_resolution_message(self, approved: bool):
        return "ID(インテンショナルドロー)が成立し、引き分けになりました。" if approved else "ID(インテンショナルドロー)は否決されました。"

    def _format_answer_result_message(self, team_label: str, is_correct: bool):
        result_label = "正解" if is_correct else "誤答"
        return f"{team_label}の解答は{result_label}でした。"

    def _format_game_finished_message(self, winner: str | None):
        if winner == "team-left":
            return "ゲーム終了！先攻の勝利"
        elif winner == "team-right":
            return "ゲーム終了！後攻の勝利"
        else:
            return "ゲーム終了！引き分け"

    def _mask_answer_text_for_viewer(self, message: str):
        text = str(message or "")
        if text == "":
            return ""
        return re.sub(r"が「[^」]*」と", "が", text)

    def _is_intentional_draw_eligible(self, room: dict):
        if not isinstance(room, dict):
            return False

        if room.get("game_state") != "playing":
            return False

        game = room.get("game") or {}
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
            return self._mask_answer_text_for_viewer(message)

        return message

    def _resolve_event_payload_for_client(
        self,
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

        # 終了時の再公開は既存仕様を維持する。
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

    async def _rebroadcast_finished_answer_logs(self, room_owner_id: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            return

        if room.get("finished_answer_logs_revealed"):
            return

        room["finished_answer_logs_revealed"] = True

        history = room.get("arena_chat_history") or []
        if not isinstance(history, list):
            return

        answer_event_types = {"answer_attempt", "answer_vote_request", "answer_vote_resolved"}
        recipients = {room_owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))

        sorted_history = sorted(
            [entry for entry in history if isinstance(entry, dict)],
            key=lambda entry: (int(entry.get("timestamp", 0)), int(entry.get("seq", 0))),
        )

        for entry in sorted_history:
            event_type = str(entry.get("event_type", "")).strip()
            event_chat_type = str(entry.get("event_chat_type", "")).strip()
            event_message = str(entry.get("event_message", "")).strip()
            if event_message == "" or event_type not in answer_event_types:
                continue
            if event_chat_type not in {"team-left", "team-right", "game-global"}:
                continue

            base_revision = max(1, int(entry.get("event_revision", 1) or 1))
            payload = entry.get("event_payload") if isinstance(entry.get("event_payload"), dict) else {}
            payload_map = payload if isinstance(payload, dict) else {}

            await self.broadcast_state(
                public_info="",
                event_type=event_type,
                event_message=event_message,
                event_chat_type=event_chat_type,
                event_room_id=room_owner_id,
                event_recipient_ids=recipients,
                event_payload={
                    **payload_map,
                    "event_id": str(entry.get("event_id") or "").strip() or None,
                    "event_revision": base_revision + 100,
                    "event_timestamp": int(entry.get("timestamp") or 0),
                    "reveal_phase": "finished",
                    "skip_history": True,
                },
            )

    # 以下、内部処理関数

    def _should_append_lobby_chat_history(self, event_type: str | None, event_chat_type: str | None, event_room_id: str | None):
        if event_room_id:
            return False

        chat_type = str(event_chat_type or "").strip()
        event_kind = str(event_type or "").strip()
        if chat_type == "lobby":
            return True
        return event_kind in {"join", "leave", "chat"}

    def _append_lobby_chat_history(
        self,
        event_type: str,
        event_message: str,
        event_chat_type: str,
        event_identity: dict | None = None,
        log_marker_id: str | None = None,
        event_timestamp: int | None = None,
    ):
        message = str(event_message or "").strip()
        if message == "":
            return

        stored_timestamp = int(event_timestamp) if isinstance(event_timestamp, int) and event_timestamp > 0 else int(time.time() * 1000)
        self.lobby_chat_seq = int(self.lobby_chat_seq) + 1
        self.lobby_chat_history.append(
            {
                "seq": int(self.lobby_chat_seq),
                "timestamp": stored_timestamp,
                "event_type": str(event_type or "").strip(),
                "event_message": message,
                "event_chat_type": str(event_chat_type or "").strip() or "lobby",
                "log_marker_id": str(log_marker_id or "").strip() or None,
                "event_id": str((event_identity or {}).get("event_id") or "").strip() or None,
                "event_revision": int((event_identity or {}).get("event_revision") or 1),
                "event_version": int((event_identity or {}).get("event_version") or 0),
            }
        )

        while len(self.lobby_chat_history) > 400:
            self.lobby_chat_history.pop(0)

    def _build_lobby_chat_history_snapshot(self):
        history = self.lobby_chat_history if isinstance(self.lobby_chat_history, list) else []
        return [entry for entry in history if isinstance(entry, dict)]

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
        room = self.rooms.get(room_owner_id)
        if room is None:
            return

        if event_chat_type not in {"team-left", "team-right", "game-global"}:
            return

        message = str(event_message or "").strip()
        if message == "":
            return

        stored_timestamp = int(event_timestamp) if isinstance(event_timestamp, int) and event_timestamp > 0 else int(time.time() * 1000)
        seq = int(room.get("arena_chat_seq", 0)) + 1
        room["arena_chat_seq"] = seq
        history = room.setdefault("arena_chat_history", [])
        if not isinstance(history, list):
            history = []
            room["arena_chat_history"] = history

        history.append(
            {
                "seq": seq,
                "timestamp": stored_timestamp,
                "event_type": str(event_type or ""),
                "event_message": message,
                "event_chat_type": event_chat_type,
                "log_marker_id": str(log_marker_id or "").strip() or None,
                "event_id": str((event_identity or {}).get("event_id") or "").strip() or None,
                "event_kind": str((event_identity or {}).get("event_kind") or event_type or "").strip() or None,
                "event_scope": str((event_identity or {}).get("event_scope") or event_chat_type or "").strip() or None,
                "event_revision": int((event_identity or {}).get("event_revision") or 1),
                "event_version": int((event_identity or {}).get("event_version") or 1),
                "event_payload": event_payload if isinstance(event_payload, dict) else None,
            }
        )

        while len(history) > 400:
            history.pop(0)

    def _purge_expired_reconnect_reservations(self):
        now = time.time()
        for reserved_client_id, reservation in list(self.reconnect_reservations.items()):
            expires_at = reservation.get("expires_at")
            if expires_at is None:
                continue
            if float(expires_at) <= now:
                self.reconnect_reservations.pop(reserved_client_id, None)

    def _clear_room_reconnect_reservations(self, room_owner_id: str):
        for reserved_client_id, reservation in list(self.reconnect_reservations.items()):
            if reservation.get("room_owner_id") == room_owner_id:
                self.reconnect_reservations.pop(reserved_client_id, None)
                self._cancel_disconnect_grace_timer(reserved_client_id)

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
        room = self.rooms.get(room_owner_id)
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

    def _clear_room_pending_disconnect(self, room_owner_id: str, client_id: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            return

        pending_disconnects = room.get("pending_disconnects")
        if not isinstance(pending_disconnects, dict):
            return

        pending_disconnects.pop(client_id, None)
        if not pending_disconnects:
            room["pending_disconnects"] = {}

    def _clear_pending_disconnect_everywhere(self, client_id: str):
        for room in self.rooms.values():
            pending_disconnects = room.get("pending_disconnects")
            if not isinstance(pending_disconnects, dict):
                continue

            pending_disconnects.pop(client_id, None)
            if not pending_disconnects:
                room["pending_disconnects"] = {}

    def _is_owner_joined_as_guest(self, room_owner_id: str, room: dict | None = None) -> bool:
        target_room = room if isinstance(room, dict) else self.rooms.get(room_owner_id)
        if target_room is None:
            return False

        return room_owner_id in target_room.get("left_participants", set()) or room_owner_id in target_room.get("right_participants", set()) or room_owner_id in target_room.get("spectators", set())

    def _reserve_participant_reconnect(self, client_id: str, ctx: dict | None):
        nickname = self.nicknames.get(client_id, "ゲスト")

        if ctx and ctx.get("role") == "participant":
            room = ctx.get("room") or {}
            if room.get("game_state") != "playing":
                return None

            team = ctx.get("chat_role")
            if team not in {"team-left", "team-right"}:
                return None

            expires_at = time.time() + self.DISCONNECT_GRACE_SECONDS
            reservation = {
                "kind": "participant",
                "room_owner_id": ctx.get("room_owner_id"),
                "team": team,
                "expires_at": expires_at,
                "nickname": nickname,
            }
            self.reconnect_reservations[client_id] = reservation
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
                self.reconnect_reservations[client_id] = reservation
                return reservation
            return None

        owned_room = self.rooms.get(client_id)
        if not isinstance(owned_room, dict):
            return None

        if not bool(owned_room.get("is_ai_mode")):
            return None

        if owned_room.get("game_state") != "playing":
            return None

        if self._is_owner_joined_as_guest(client_id, owned_room):
            return None

        reservation = {
            "kind": "owner",
            "room_owner_id": client_id,
            "team": "questioner",
            "expires_at": None,
            "nickname": nickname,
        }
        self.reconnect_reservations[client_id] = reservation
        return reservation

    def _try_restore_participant_reconnect(self, client_id: str):
        self._purge_expired_reconnect_reservations()

        reservation = self.reconnect_reservations.get(client_id)
        if not reservation:
            return None

        kind = str(reservation.get("kind") or "participant")
        room_owner_id = reservation.get("room_owner_id")
        room = self.rooms.get(room_owner_id)
        if room is None:
            self.reconnect_reservations.pop(client_id, None)
            return None

        if kind == "owner":
            self.reconnect_reservations.pop(client_id, None)
            self._cancel_disconnect_grace_timer(client_id)
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
            self.reconnect_reservations.pop(client_id, None)
            return None

        self.reconnect_reservations.pop(client_id, None)
        self._clear_room_pending_disconnect(room_owner_id, client_id)
        self._cancel_disconnect_grace_timer(client_id)
        return {
            "room_owner_id": room_owner_id,
            "kind": "participant",
        }

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
        wait_seconds = max(0.0, expires_at - time.time())
        try:
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            if client_id in self.active_connections:
                return

            reservation = self.reconnect_reservations.get(client_id)
            if not reservation:
                return

            if str(reservation.get("kind") or "participant") != "participant":
                return

            if reservation.get("room_owner_id") != room_owner_id:
                return

            room = self.rooms.get(room_owner_id)
            if room is None:
                self.reconnect_reservations.pop(client_id, None)
                return

            self.reconnect_reservations.pop(client_id, None)
            self._clear_room_pending_disconnect(room_owner_id, client_id)

            room["left_participants"].discard(client_id)
            room["right_participants"].discard(client_id)
            room["spectators"].discard(client_id)

            await self.broadcast_state(
                public_info=f"{nickname} の再接続猶予が切れ、部屋から退室しました。",
                event_type="participant_timeout_expired",
                event_message=f"{nickname} の接続タイムアウト猶予が終了しました。",
                event_room_id=room_owner_id,
            )

            await self._evaluate_team_forfeit_if_needed(room_owner_id, room)

        except asyncio.CancelledError:
            pass
        finally:
            active_task = self.pending_disconnect_tasks.get(client_id)
            if active_task is asyncio.current_task():
                self.pending_disconnect_tasks.pop(client_id, None)

    def _schedule_participant_disconnect_grace(
        self,
        client_id: str,
        room_owner_id: str,
        expires_at: float,
        nickname: str,
    ):
        self._cancel_disconnect_grace_timer(client_id)
        task = asyncio.create_task(
            self._finalize_participant_disconnect_after_grace(
                client_id,
                room_owner_id,
                expires_at,
                nickname,
            )
        )
        self.pending_disconnect_tasks[client_id] = task

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

    async def request_open_vote(self, client_id: str, char_index):
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]

        team = self._resolve_team_for_client(room, client_id)
        if team is None:
            await self.send_private_info(client_id, "陣営参加者のみオープンを申請できます。")
            return

        if room.get("game_state") != "playing":
            await self.send_private_info(client_id, "ゲーム開始後に操作できます。")
            return

        game = room.get("game") or {}
        if game.get("pending_answer_judgement") is not None:
            await self.send_private_info(client_id, "正誤判定中は行動できません。")
            return

        pending_answer_vote = room.get("pending_answer_vote")
        if pending_answer_vote and pending_answer_vote.get("status") == "pending":
            await self.send_private_info(client_id, "進行中のアンサー投票があります。")
            return

        pending_turn_end_vote = room.get("pending_turn_end_vote")
        if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
            await self.send_private_info(client_id, "進行中のターンエンド投票があります。")
            return

        pending_intentional_draw_vote = room.get("pending_intentional_draw_vote")
        if pending_intentional_draw_vote and pending_intentional_draw_vote.get("status") == "pending":
            await self.send_private_info(client_id, "ID(インテンショナルドロー)投票中はオープンを申請できません。")
            return

        if game.get("current_turn_team") != team:
            await self.send_private_info(client_id, "あなたの陣営のターンではありません。")
            return

        if not isinstance(char_index, int):
            await self.send_private_info(client_id, "無効な文字インデックスです。")
            return

        question_length = len(_normalized_question_chars(room.get("question_text", "")))
        if char_index < 0 or char_index >= question_length:
            await self.send_private_info(client_id, "無効な文字インデックスです。")
            return

        pending_vote = room.get("pending_open_vote")
        if pending_vote and pending_vote.get("status") == "pending":
            await self.send_private_info(client_id, "進行中のオープン投票があります。")
            return

        voter_ids = self._get_team_participant_ids(room, team)
        if not voter_ids:
            await self.send_private_info(client_id, "投票対象の陣営参加者がいません。")
            return

        total_voters = len(voter_ids)
        open_log_recipient_ids = {owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))
        team_label = self._team_label(team)

        if total_voters == 1:
            previous_turn_team = (room.get("game") or {}).get("current_turn_team")
            result = apply_open_character(room, team, char_index)
            vote_id = str(uuid.uuid4())

            if not result.get("ok"):
                await self.broadcast_state(
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
            await self.broadcast_state(
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

            await self.broadcast_state(
                public_info=f"{char_index + 1}文字目がオープンされました。",
                event_type="character_opened",
                event_message=self._format_open_vote_resolution_message(team_label, char_index, True),
                event_chat_type="game-global",
                event_room_id=owner_id,
                event_recipient_ids=open_log_recipient_ids,
                event_payload={
                    "team": team,
                    "char_index": char_index,
                    "is_yakumono": is_yakumono,
                },
            )
            self._append_kifu_action(
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
                turn_changed_message = self._format_turn_changed_message(next_turn_team)
                await self.broadcast_state(
                    public_info=turn_changed_message,
                    event_type="turn_changed",
                    event_room_id=owner_id,
                )
                await self._broadcast_team_log_message(owner_id, room, "turn_changed", turn_changed_message)
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

        request_public_info = ""
        request_event_message = ""
        await self.broadcast_state(
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
            await self.send_private_info(client_id, "提案しました。")

    async def respond_open_vote(self, client_id: str, vote_id: str, approve: bool):
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        pending_vote = room.get("pending_open_vote")

        if not pending_vote or pending_vote.get("status") != "pending":
            await self.send_private_info(client_id, "進行中の投票がありません。")
            return

        if pending_vote.get("vote_id") != vote_id:
            await self.send_private_info(client_id, "投票IDが一致しません。")
            return

        voter_ids = pending_vote["voter_ids"]
        if client_id not in voter_ids:
            await self.send_private_info(client_id, "この投票には参加できません。")
            return

        if client_id in pending_vote["approved_ids"] or client_id in pending_vote["rejected_ids"]:
            await self.send_private_info(client_id, "この投票にはすでに回答済みです。")
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
        team_label = self._team_label(team)
        open_log_recipient_ids = {owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))

        if approvals >= required:
            pending_vote["status"] = "approved"
            previous_turn_team = (room.get("game") or {}).get("current_turn_team")
            result = apply_open_character(room, team, char_index)
            room["pending_open_vote"] = None

            if not result.get("ok"):
                await self.broadcast_state(
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
            await self.broadcast_state(
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

            await self.broadcast_state(
                public_info=f"{char_index + 1}文字目がオープンされました。",
                event_type="character_opened",
                event_message=self._format_open_vote_resolution_message(team_label, char_index, True),
                event_chat_type="game-global",
                event_room_id=owner_id,
                event_recipient_ids=open_log_recipient_ids,
                event_payload={
                    "team": team,
                    "char_index": char_index,
                    "is_yakumono": is_yakumono,
                },
            )
            self._append_kifu_action(
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
                turn_changed_message = self._format_turn_changed_message(next_turn_team)
                await self.broadcast_state(
                    public_info=turn_changed_message,
                    event_type="turn_changed",
                    event_room_id=owner_id,
                )
                await self._broadcast_team_log_message(owner_id, room, "turn_changed", turn_changed_message)
            return

        max_possible_approvals = approvals + (len(voter_ids) - approvals - rejections)
        if max_possible_approvals < required:
            pending_vote["status"] = "rejected"
            room["pending_open_vote"] = None
            await self.broadcast_state(
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
            await self.broadcast_state(
                public_info="",
                private_map=private_map,
                event_type="private_notice",
                event_room_id=owner_id,
            )

    async def respond_answer_vote(self, client_id: str, vote_id: str, approve: bool):
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        pending_vote = room.get("pending_answer_vote")

        if not pending_vote or pending_vote.get("status") != "pending":
            await self.send_private_info(client_id, "進行中のアンサー投票がありません。")
            return

        if pending_vote.get("vote_id") != vote_id:
            await self.send_private_info(client_id, "投票IDが一致しません。")
            return

        voter_ids = pending_vote["voter_ids"]
        if client_id not in voter_ids:
            await self.send_private_info(client_id, "この投票には参加できません。")
            return

        if client_id in pending_vote["approved_ids"] or client_id in pending_vote["rejected_ids"]:
            await self.send_private_info(client_id, "この投票にはすでに回答済みです。")
            return

        if approve:
            pending_vote["approved_ids"].add(client_id)
        else:
            pending_vote["rejected_ids"].add(client_id)

        approvals = len(pending_vote["approved_ids"])
        rejections = len(pending_vote["rejected_ids"])
        required = pending_vote["required_approvals"]
        team = pending_vote["team"]
        team_label = self._team_label(team)
        should_emit_vote_log = len(voter_ids) > 1
        answer_text = str(pending_vote.get("answer_text", "")).strip()
        requester_id = pending_vote.get("requester_id")
        requester_name = self.nicknames.get(requester_id, "ゲスト")

        team_chat_recipients = set(voter_ids)
        team_chat_result = resolve_chat_recipients(owner_id, room, team, team)
        if team_chat_result.get("ok"):
            team_chat_recipients = team_chat_result["event_recipient_ids"]

        if approvals >= required:
            pending_vote["status"] = "approved"
            room["pending_answer_vote"] = None

            game = room.get("game") or {}
            if game.get("pending_answer_judgement") is not None:
                await self.broadcast_state(
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
            self._append_kifu_action(
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
                await self.broadcast_state(
                    public_info=f"{team_label}が解答を提出しました。出題者が正誤判定中です。",
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
                self._format_answer_attempt_message(team_label, answer_text),
                event_payload={
                    "team": team,
                    "log_marker_id": answer_log_marker_id,
                },
            )

            await self.broadcast_state(
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
                await self._resolve_ai_answer_judgement(owner_id, room, team, answer_text)
                return

            await self.broadcast_state(
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
            await self.broadcast_state(
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
            await self.broadcast_state(
                public_info="",
                private_map=private_map,
                event_type="private_notice",
                event_room_id=owner_id,
            )
            return

    async def request_turn_end_attempt(self, client_id: str):
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        if room.get("game_state") != "playing":
            await self.send_private_info(client_id, "対戦中のみターンエンドできます。")
            return

        game = room.get("game") or {}
        if game.get("pending_answer_judgement") is not None:
            await self.send_private_info(client_id, "正誤判定中は行動できません。")
            return

        pending_open_vote = room.get("pending_open_vote")
        if pending_open_vote and pending_open_vote.get("status") == "pending":
            await self.send_private_info(client_id, "文字オープン投票中はターンエンドできません。")
            return

        pending_answer_vote = room.get("pending_answer_vote")
        if pending_answer_vote and pending_answer_vote.get("status") == "pending":
            await self.send_private_info(client_id, "アンサー投票中はターンエンドできません。")
            return

        pending_turn_end_vote = room.get("pending_turn_end_vote")
        if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
            await self.send_private_info(client_id, "進行中のターンエンド投票があります。")
            return

        pending_intentional_draw_vote = room.get("pending_intentional_draw_vote")
        if pending_intentional_draw_vote and pending_intentional_draw_vote.get("status") == "pending":
            await self.send_private_info(client_id, "ID(インテンショナルドロー)投票中はターンエンドできません。")
            return

        team = self._resolve_team_for_client(room, client_id)
        if team is None:
            await self.send_private_info(client_id, "参加者のみターンエンドできます。")
            return

        if game.get("current_turn_team") != team:
            await self.send_private_info(client_id, "自分のターンでのみターンエンドできます。")
            return

        voter_ids = self._get_team_participant_ids(room, team)
        if not voter_ids:
            await self.send_private_info(client_id, "投票対象の陣営参加者がいません。")
            return

        total_voters = len(voter_ids)
        if total_voters == 1:
            result = apply_end_turn(room, team)
            if not result.get("ok"):
                await self.send_private_info(client_id, result.get("error", "ターン終了に失敗しました。"))
                return

            self._append_kifu_action(
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
                game_finished_message = self._format_game_finished_message(winner)
                await self._broadcast_game_finished_message(owner_id, room, game_finished_message)
                self._finalize_kifu_if_tracking(owner_id, room, "finished")
            else:
                next_team = result.get("current_turn_team")
                turn_changed_message = self._format_turn_changed_message(next_team)
                await self.broadcast_state(
                    public_info=turn_changed_message,
                    event_type="turn_changed",
                    event_room_id=owner_id,
                )
                await self._broadcast_team_log_message(owner_id, room, "turn_changed", turn_changed_message)
            await self.send_private_info(client_id, "ターンエンドしました。")
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

        team_label = self._team_label(team)
        requester_name = self.nicknames.get(client_id, "ゲスト")
        await self.broadcast_state(
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

        await self.send_private_info(client_id, "提案しました。")

    async def request_intentional_draw_vote(self, client_id: str):
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]

        if room.get("game_state") != "playing":
            await self.send_private_info(client_id, "対戦中のみID(インテンショナルドロー)を提案できます。")
            return

        game = room.get("game") or {}
        if game.get("pending_answer_judgement") is not None:
            await self.send_private_info(client_id, "正誤判定中はID(インテンショナルドロー)を提案できません。")
            return

        pending_open_vote = room.get("pending_open_vote")
        if pending_open_vote and pending_open_vote.get("status") == "pending":
            await self.send_private_info(client_id, "文字オープン投票中はID(インテンショナルドロー)を提案できません。")
            return

        pending_answer_vote = room.get("pending_answer_vote")
        if pending_answer_vote and pending_answer_vote.get("status") == "pending":
            await self.send_private_info(client_id, "アンサー投票中はID(インテンショナルドロー)を提案できません。")
            return

        pending_turn_end_vote = room.get("pending_turn_end_vote")
        if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
            await self.send_private_info(client_id, "ターンエンド投票中はID(インテンショナルドロー)を提案できません。")
            return

        pending_intentional_draw_vote = room.get("pending_intentional_draw_vote")
        if pending_intentional_draw_vote and pending_intentional_draw_vote.get("status") == "pending":
            await self.send_private_info(client_id, "進行中のID(インテンショナルドロー)投票があります。")
            return

        if not self._is_intentional_draw_eligible(room):
            await self.send_private_info(client_id, "ID(インテンショナルドロー)を提案できる条件を満たしていません。")
            return

        voter_ids = set(room.get("left_participants", set())) | set(room.get("right_participants", set()))
        if not voter_ids:
            await self.send_private_info(client_id, "投票対象の参加者がいません。")
            return

        vote_id = str(uuid.uuid4())
        required_approvals = len(voter_ids)
        requester_name = self.nicknames.get(client_id, "ゲスト")
        room["pending_intentional_draw_vote"] = {
            "vote_id": vote_id,
            "requester_id": client_id,
            "voter_ids": voter_ids,
            "approved_ids": ({client_id} if client_id in voter_ids else set()),
            "rejected_ids": set(),
            "required_approvals": required_approvals,
            "status": "pending",
        }

        await self.broadcast_state(
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

        await self.send_private_info(client_id, "ID(インテンショナルドロー)を提案しました。")

    async def respond_intentional_draw_vote(self, client_id: str, vote_id: str, approve: bool):
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        pending_vote = room.get("pending_intentional_draw_vote")

        if not pending_vote or pending_vote.get("status") != "pending":
            await self.send_private_info(client_id, "進行中のID(インテンショナルドロー)投票がありません。")
            return

        if pending_vote.get("vote_id") != vote_id:
            await self.send_private_info(client_id, "投票IDが一致しません。")
            return

        voter_ids = set(pending_vote.get("voter_ids", set()))
        if client_id not in voter_ids:
            await self.send_private_info(client_id, "この投票には参加できません。")
            return

        approved_ids = set(pending_vote.get("approved_ids", set()))
        rejected_ids = set(pending_vote.get("rejected_ids", set()))
        if client_id in approved_ids or client_id in rejected_ids:
            await self.send_private_info(client_id, "この投票にはすでに回答済みです。")
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

            game = room.get("game") or {}
            self._append_kifu_action(
                owner_id,
                "intentional_draw",
                "game-global",
                pending_vote.get("requester_id"),
                {
                    "proposed_by_vote": True,
                    "vote_id": vote_id,
                },
            )
            game["winner"] = "draw"
            game["game_status"] = "finished"
            game["left_correct_waiting"] = False
            game["pending_answer_judgement"] = None
            room["game_state"] = "finished"
            room["pending_open_vote"] = None
            room["pending_answer_vote"] = None
            room["pending_turn_end_vote"] = None

            await self.broadcast_state(
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

            await self.broadcast_state(
                public_info="ID(インテンショナルドロー)が成立しました。",
                event_type="intentional_draw",
                event_message="IDが成立しました。",
                event_chat_type="game-global",
                event_room_id=owner_id,
                event_recipient_ids=recipients,
                event_payload={
                    "vote_id": vote_id,
                    "log_marker_id": vote_id,
                },
            )

            game_finished_message = self._format_game_finished_message("draw")
            await self._broadcast_game_finished_message(owner_id, room, game_finished_message)
            self._finalize_kifu_if_tracking(owner_id, room, "intentional_draw")
            return

        if len(rejected_ids) > 0:
            pending_vote["status"] = "rejected"
            room["pending_intentional_draw_vote"] = None
            await self.broadcast_state(
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
            private_map = {target_id: "ID(インテンショナルドロー)の提案が否決されました。" for target_id in notify_targets}
            await self.broadcast_state(
                public_info="",
                private_map=private_map,
                event_type="private_notice",
                event_room_id=owner_id,
            )
            return

    async def respond_turn_end_vote(self, client_id: str, vote_id: str, approve: bool):
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        pending_vote = room.get("pending_turn_end_vote")

        if not pending_vote or pending_vote.get("status") != "pending":
            await self.send_private_info(client_id, "進行中のターンエンド投票がありません。")
            return

        if pending_vote.get("vote_id") != vote_id:
            await self.send_private_info(client_id, "投票IDが一致しません。")
            return

        voter_ids = pending_vote["voter_ids"]
        if client_id not in voter_ids:
            await self.send_private_info(client_id, "この投票には参加できません。")
            return

        if client_id in pending_vote["approved_ids"] or client_id in pending_vote["rejected_ids"]:
            await self.send_private_info(client_id, "この投票にはすでに回答済みです。")
            return

        if approve:
            pending_vote["approved_ids"].add(client_id)
        else:
            pending_vote["rejected_ids"].add(client_id)

        approvals = len(pending_vote["approved_ids"])
        rejections = len(pending_vote["rejected_ids"])
        required = pending_vote["required_approvals"]
        team = pending_vote["team"]
        team_label = self._team_label(team)

        team_chat_recipients = set(voter_ids)
        team_chat_result = resolve_chat_recipients(owner_id, room, team, team)
        if team_chat_result.get("ok"):
            team_chat_recipients = team_chat_result["event_recipient_ids"]

        if approvals >= required:
            pending_vote["status"] = "approved"
            room["pending_turn_end_vote"] = None

            result = apply_end_turn(room, team)
            if not result.get("ok"):
                await self.broadcast_state(
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

            self._append_kifu_action(
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

            await self.broadcast_state(
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
                game_finished_message = self._format_game_finished_message(winner)
                await self._broadcast_game_finished_message(owner_id, room, game_finished_message)
                self._finalize_kifu_if_tracking(owner_id, room, "finished")
            else:
                next_team = result.get("current_turn_team")
                turn_changed_message = self._format_turn_changed_message(next_team)
                await self.broadcast_state(
                    public_info=turn_changed_message,
                    event_type="turn_changed",
                    event_room_id=owner_id,
                )
                await self._broadcast_team_log_message(owner_id, room, "turn_changed", turn_changed_message)
            return

        max_possible_approvals = approvals + (len(voter_ids) - approvals - rejections)
        if max_possible_approvals < required:
            pending_vote["status"] = "rejected"
            room["pending_turn_end_vote"] = None
            await self.broadcast_state(
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

    async def send_private_info(
        self,
        client_id: str,
        message: str,
        target_screen: str | None = None,
        event_type: str = "private_notice",
    ):
        ws = self.active_connections.get(client_id)
        if ws is None:
            return

        response = {
            "public_info": "",
            "private_info": message,
            "participants": self.build_participants(),
            "rooms": self.build_rooms_summary(client_id),
            "current_room": self.build_current_room_for_client(client_id),
            "lobby_chat_history": self._build_lobby_chat_history_snapshot(),
            "event_type": event_type,
            "event_message": None,
            "event_chat_type": None,
            "event_room_id": None,
            "target_screen": target_screen,
        }
        await ws.send_text(json.dumps(response))

    async def cancel_question(self, requester_id: str, room_owner_id: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            await self.send_private_info(requester_id, "取り消し対象の部屋が見つかりません。")
            return

        if requester_id != room_owner_id:
            await self.send_private_info(requester_id, "出題取消は出題者のみ実行できます。")
            return

        questioner_name = room["questioner_name"]
        # 強制退室通知は参加者・観戦者のみに送り、出題者本人には送らない。
        affected_client_ids = set(room["left_participants"]) | set(room["right_participants"]) | set(room["spectators"])
        affected_client_ids.discard(requester_id)
        self.rooms.pop(room_owner_id, None)
        self._finalize_kifu_if_tracking(room_owner_id, room, "owner_cancelled")
        self._clear_room_reconnect_reservations(room_owner_id)

        await self.send_private_info(
            requester_id,
            "部屋を閉じました。",
            target_screen="waiting_room",
            event_type="room_closed",
        )

        for target_client_id in affected_client_ids:
            await self.send_private_info(
                target_client_id,
                "出題が取り消されたため、部屋から退室しました。",
                target_screen="waiting_room",
                event_type="forced_exit_notice",
            )

        await self.broadcast_state(
            public_info=f"{questioner_name} の出題が取り消されました",
            event_type="room_closed",
            event_message=f"{questioner_name} が出題を取り消しました",
            event_room_id=room_owner_id,
        )

    def remove_client_from_all_rooms(self, client_id: str):
        remove_client_from_all_rooms_logic(self.rooms, client_id)

    async def join_room(self, client_id: str, room_owner_id: str, role: str):
        self._cancel_disconnect_grace_timer(client_id)
        self._clear_pending_disconnect_everywhere(client_id)
        self.reconnect_reservations.pop(client_id, None)
        result = apply_join_room(self.rooms, client_id, room_owner_id, role)
        if not result.get("ok"):
            await self.send_private_info(client_id, result.get("error", "部屋への入室に失敗しました。"))
            return

        await self.send_private_info(
            client_id,
            result.get("entry_message", "部屋に入りました。"),
            target_screen=result.get("target_screen"),
        )

        joined_ctx = resolve_client_room_context(self.rooms, client_id)
        if result.get("target_screen") == "game_arena" and joined_ctx is not None and joined_ctx.get("role") == "participant" and joined_ctx.get("room_owner_id") == room_owner_id:
            await self._resend_pending_votes_to_client(room_owner_id, client_id)

        role_name = result.get("event_role_name")
        if role_name is None:
            return

        room = self.rooms.get(room_owner_id)
        if room is None:
            return

        joined_ctx = resolve_client_room_context(self.rooms, client_id)
        if joined_ctx is not None and joined_ctx.get("room_owner_id") == room_owner_id and joined_ctx.get("role") == "spectator" and room.get("game_state") in {"playing", "finished"}:
            self._touch_kifu_spectator_if_tracking(room_owner_id, client_id)

        nickname = self.nicknames.get(client_id, "ゲスト")
        await self.broadcast_state(
            public_info=f"{nickname} が部屋に入りました",
            event_type="room_entry",
            event_message=f"{nickname} が {room['questioner_name']} の部屋に{role_name}として参加しました",
            event_room_id=room_owner_id,
        )

    async def start_game(self, client_id: str, payload: dict | None = None):
        result = apply_start_game(self.rooms, client_id, payload)
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

    async def shuffle_participants(self, client_id: str):
        result = apply_shuffle_participants(self.rooms, client_id)
        if not result.get("ok"):
            await self.send_private_info(client_id, result.get("error", "参加者シャッフルに失敗しました。"))
            return

        room = self.rooms.get(client_id)
        is_ai_mode = bool(room and room.get("is_ai_mode"))
        actor_name = self.nicknames.get(client_id, "ゲスト") if is_ai_mode else result["questioner_name"]
        await self.broadcast_state(
            public_info=f"{actor_name} が参加者をシャッフルしました",
            event_type="room_shuffle",
            event_message=f"{actor_name} が参加者をシャッフルしました",
            event_room_id=client_id,
        )

    async def swap_participant_team(self, client_id: str, target_client_id: str):
        result = apply_swap_participant_team(self.rooms, client_id, target_client_id)
        if not result.get("ok"):
            await self.send_private_info(client_id, result.get("error", "参加者入れ替えに失敗しました。"))
            return

        room = self.rooms.get(client_id)
        is_ai_mode = bool(room and room.get("is_ai_mode"))
        actor_name = self.nicknames.get(client_id, "ゲスト") if is_ai_mode else result["questioner_name"]
        target_id = str(result.get("target_client_id") or "").strip()
        from_team = str(result.get("from_team") or "")
        to_team = str(result.get("to_team") or "")
        target_name = self.nicknames.get(target_id, "ゲスト")
        from_label = self._team_label(from_team)
        to_label = self._team_label(to_team)

        await self.broadcast_state(
            public_info=f"{actor_name} が参加者を入れ替えました",
            event_type="room_shuffle",
            event_message=f"{actor_name} が {target_name} を {from_label}から{to_label} に入れ替えました",
            event_room_id=client_id,
        )

    async def open_character(self, client_id: str, char_index):
        """文字をオープンするアクション"""
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]
        if (room.get("game") or {}).get("pending_answer_judgement") is not None:
            await self.send_private_info(client_id, "正誤判定中は行動できません。")
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

    async def submit_answer(self, client_id: str, is_correct: bool):
        """レガシーメソッド: 実際の判定処理はjudge_answer()に委譲"""
        await self.judge_answer(client_id, is_correct)

    async def end_turn(self, client_id: str):
        """互換のため残す: 実体はターンエンド提案処理"""
        await self.request_turn_end_attempt(client_id)

    async def submit_answer_attempt(self, client_id: str, answer_text: str):
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
            await self.send_private_info(client_id, "ID(インテンショナルドロー)投票中は解答を送信できません。")
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

    async def judge_answer(self, client_id: str, is_correct: bool):
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

    async def connect(self, websocket: WebSocket, client_id: str, nickname: str):
        # 同一 client_id の二重接続は許可しない（別タブ重複やなりすまし抑止）。
        if client_id in self.active_connections:
            await websocket.close(code=1008, reason="Duplicate session")
            print(f"接続拒否（重複client_id）: {client_id}")
            return False

        # 接続上限に達している場合は、即座に通信を切断する
        if len(self.active_connections) >= self.MAX_CONNECTIONS:
            # WebSocketのステータスコード1008は「ポリシー違反（リソース超過など）」を意味します
            await websocket.close(code=1008, reason="Server is full or Rate limited")
            print(f"接続拒否（満員）: {client_id}")
            return False

        await websocket.accept()

        self.active_connections[client_id] = websocket
        self.nicknames[client_id] = nickname
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

    async def exit_room(self, client_id: str):
        ctx_before_exit = resolve_client_room_context(self.rooms, client_id)
        room_owner_id_before_exit = ctx_before_exit.get("room_owner_id") if ctx_before_exit else None

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

    async def process_question(self, player_id: str, payload: dict):
        normalized_payload = dict(payload or {})
        is_ai_mode = bool(normalized_payload.get("is_ai_mode"))
        model_id = normalize_model_id(normalized_payload.get("model_id"))
        requester_name = self.nicknames.get(player_id, "ゲスト")

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

    async def process_chat_message(self, client_id: str, payload: dict):
        message = str(payload.get("message", "")).replace("\r\n", "\n").replace("\r", "\n").strip()
        if message == "":
            return

        chat_type = str(payload.get("chat_type", "lobby")).strip() or "lobby"

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
        payload_type = payload.get("type")

        if payload_type == "room_exit":
            await self.exit_room(client_id)
            return

        if payload_type == "question_submission":
            await self.process_question(client_id, payload)
            return

        if payload_type == "chat_message":
            await self.process_chat_message(client_id, payload)
            return

        if payload_type == "start_game":
            await self.start_game(client_id, payload)
            return

        if payload_type == "shuffle_participants":
            await self.shuffle_participants(client_id)
            return

        if payload_type == "swap_participant_team":
            target_client_id = str(payload.get("target_client_id", "")).strip()
            await self.swap_participant_team(client_id, target_client_id)
            return

        if payload_type == "open_character":
            char_index = payload.get("char_index")
            await self.open_character(client_id, char_index)
            return

        if payload_type == "open_vote_request":
            char_index = payload.get("char_index")
            await self.request_open_vote(client_id, char_index)
            return

        if payload_type == "open_vote_response":
            vote_id = str(payload.get("vote_id", "")).strip()
            approve = bool(payload.get("approve", False))
            if vote_id == "":
                await self.send_private_info(client_id, "投票IDが不正です。")
                return
            await self.respond_open_vote(client_id, vote_id, approve)
            return

        if payload_type == "answer_vote_response":
            vote_id = str(payload.get("vote_id", "")).strip()
            approve = bool(payload.get("approve", False))
            if vote_id == "":
                await self.send_private_info(client_id, "投票IDが不正です。")
                return
            await self.respond_answer_vote(client_id, vote_id, approve)
            return

        if payload_type == "turn_end_vote_response":
            vote_id = str(payload.get("vote_id", "")).strip()
            approve = bool(payload.get("approve", False))
            if vote_id == "":
                await self.send_private_info(client_id, "投票IDが不正です。")
                return
            await self.respond_turn_end_vote(client_id, vote_id, approve)
            return

        if payload_type == "intentional_draw_vote_request":
            await self.request_intentional_draw_vote(client_id)
            return

        if payload_type == "intentional_draw_vote_response":
            vote_id = str(payload.get("vote_id", "")).strip()
            approve = bool(payload.get("approve", False))
            if vote_id == "":
                await self.send_private_info(client_id, "投票IDが不正です。")
                return
            await self.respond_intentional_draw_vote(client_id, vote_id, approve)
            return

        if payload_type == "submit_answer":
            is_correct = payload.get("is_correct", False)
            await self.submit_answer(client_id, is_correct)
            return

        if payload_type == "answer_attempt":
            answer_text = str(payload.get("answer_text", ""))
            await self.submit_answer_attempt(client_id, answer_text)
            return

        if payload_type == "judge_answer":
            is_correct = bool(payload.get("is_correct", False))
            await self.judge_answer(client_id, is_correct)
            return

        if payload_type == "end_turn" or payload_type == "turn_end_attempt":
            await self.request_turn_end_attempt(client_id)
            return

        if payload_type == "room_entry":
            room_owner_id = str(payload.get("room_owner_id", "")).strip()
            role = str(payload.get("role", "")).strip()
            if room_owner_id == "" or role not in {"participant", "spectator"}:
                await self.send_private_info(client_id, "入室リクエストの形式が不正です。")
                return

            await self.join_room(client_id, room_owner_id, role)
            return

        if payload_type == "cancel_question":
            room_owner_id = str(payload.get("room_owner_id", "")).strip()
            if room_owner_id == "":
                await self.send_private_info(client_id, "出題取消リクエストの形式が不正です。")
                return

            await self.cancel_question(client_id, room_owner_id)
            return

        # 旧フォーマット互換: typeなしでも問題送信として扱う。
        if "question_text" in payload or "content" in payload:
            await self.process_question(client_id, payload)
            return

        await self.send_private_info(client_id, "未対応のメッセージ形式です。")


manager = QuizGameManager()
ws_auth_manager = WebSocketAuthManager()


def _resolve_active_client_or_401(client_id: str) -> str:
    cid = str(client_id or "").strip()
    if not is_valid_client_id(cid):
        diag_api_log("auth_check", path="kifu", client_id=cid, valid_client_id=False, connected=False, status=400)
        raise HTTPException(status_code=400, detail="invalid_client_id")
    if cid not in manager.active_connections:
        diag_api_log("auth_check", path="kifu", client_id=cid, valid_client_id=True, connected=False, status=401)
        raise HTTPException(status_code=401, detail="not_connected")
    diag_api_log("auth_check", path="kifu", client_id=cid, valid_client_id=True, connected=True, status=200)
    return cid


@app.get("/api/kifu/list")
async def kifu_list(client_id: str = Query(...)):
    cid = _resolve_active_client_or_401(client_id)
    return {"kifu": list_kifu_for_client(cid)}


@app.get("/api/kifu/{kifu_id}")
async def kifu_detail(kifu_id: str, client_id: str = Query(...)):
    cid = _resolve_active_client_or_401(client_id)
    detail = get_kifu_detail_for_client(kifu_id, cid)
    if detail is None:
        raise HTTPException(status_code=404, detail="kifu_not_found")
    if detail == {}:
        raise HTTPException(status_code=403, detail="forbidden")
    return detail


@app.post("/api/ws-ticket")
async def issue_ws_ticket(request: WsTicketIssueRequest):
    client_id = str(request.client_id or "").strip()
    nickname = sanitize_nickname(request.nickname)

    if not is_valid_client_id(client_id):
        raise HTTPException(status_code=400, detail="invalid_client_id")

    if client_id in manager.active_connections:
        raise HTTPException(status_code=409, detail="already_connected")

    ticket_payload = ws_auth_manager.issue_ticket(client_id, nickname)
    ticket_payload["nickname"] = nickname
    return ticket_payload


@app.get("/api/ai-models")
async def get_ai_models():
    diag_api_log("ai_models", connected_count=len(manager.active_connections), status=200)
    return get_frontend_model_payload()


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    client_id = str(client_id or "").strip()
    nickname = sanitize_nickname(websocket.query_params.get("nickname", "ゲスト"))
    ws_ticket = str(websocket.query_params.get("ws_ticket", "")).strip()

    if not is_valid_client_id(client_id):
        await websocket.close(code=1008, reason="Invalid client id")
        return

    is_valid_ticket, reason = ws_auth_manager.verify_ticket(ws_ticket, client_id, nickname)
    if not is_valid_ticket:
        await websocket.close(code=1008, reason=f"Unauthorized: {reason}")
        return

    # 接続処理を行い、許可されなかった（False）場合はここで処理を終える
    is_accepted = await manager.connect(websocket, client_id, nickname)
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

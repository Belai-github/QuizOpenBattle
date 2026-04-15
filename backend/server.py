from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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

app = FastAPI()

app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")


CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
MAX_NICKNAME_LENGTH = 24


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
        # 【対策1】同時に接続できる最大人数を設定
        self.MAX_CONNECTIONS = 4
        self.RECONNECT_RESERVATION_SECONDS = 120
        self.DISCONNECT_GRACE_SECONDS = 30
        self.CHAT_MAX_LENGTH = 200
        self.ANSWER_MAX_LENGTH = 100
        self.CHAT_MIN_INTERVAL_SECONDS = 0.8
        self.CHAT_RATE_WINDOW_SECONDS = 10.0
        self.CHAT_RATE_WINDOW_MAX_MESSAGES = 5
        self.chat_message_history = {}
        self.chat_last_message = {}

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
                    "questioner_name": room["questioner_name"],
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
            "turn_changed",
            "room_reconnected",
        }
        history_message = str(event_message or public_info or "").strip()

        if event_room_id and history_message:
            if event_chat_type in {"team-left", "team-right", "game-global"}:
                self._append_arena_chat_history(event_room_id, event_type or "", history_message, event_chat_type)
            elif event_type in {"room_entry", "room_exit"}:
                self._append_arena_chat_history(event_room_id, event_type, history_message, "game-global")
            elif event_type in arena_progress_event_types:
                self._append_arena_chat_history(event_room_id, event_type or "", history_message, "game-global")

        participants = self.build_participants()
        for client_id, ws in self.active_connections.items():
            rooms = self.build_rooms_summary(client_id)
            current_room = self.build_current_room_for_client(client_id)
            private_info = ""
            if private_map is not None:
                private_info = private_map.get(client_id, "")

            is_event_recipient = event_recipient_ids is None or client_id in event_recipient_ids
            response_event_type = event_type if is_event_recipient else None
            response_event_message = history_message if is_event_recipient else None
            response_event_chat_type = event_chat_type if is_event_recipient else None

            response = {
                "public_info": public_info,
                "private_info": private_info,
                "participants": participants,
                "rooms": rooms,
                "current_room": current_room,
                "event_type": response_event_type,
                "event_message": response_event_message,
                "event_chat_type": response_event_chat_type,
                "event_room_id": event_room_id,
                "target_screen": target_screen,
                "event_payload": event_payload if is_event_recipient else None,
            }
            await ws.send_text(json.dumps(response))

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

    def _append_arena_chat_history(self, room_owner_id: str, event_type: str, event_message: str, event_chat_type: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            return

        if event_chat_type not in {"team-left", "team-right", "game-global"}:
            return

        message = str(event_message or "").strip()
        if message == "":
            return

        seq = int(room.get("arena_chat_seq", 0)) + 1
        room["arena_chat_seq"] = seq
        history = room.setdefault("arena_chat_history", [])
        if not isinstance(history, list):
            history = []
            room["arena_chat_history"] = history

        history.append(
            {
                "seq": seq,
                "timestamp": int(time.time() * 1000),
                "event_type": str(event_type or ""),
                "event_message": message,
                "event_chat_type": event_chat_type,
            }
        )

        while len(history) > 400:
            history.pop(0)

    def _purge_expired_reconnect_reservations(self):
        now = time.time()
        for reserved_client_id, reservation in list(self.reconnect_reservations.items()):
            if reservation.get("expires_at", 0) <= now:
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

    def _reserve_participant_reconnect(self, client_id: str, ctx: dict | None):
        if not ctx or ctx.get("role") != "participant":
            return None

        room = ctx.get("room") or {}
        if room.get("game_state") != "playing":
            return None

        team = ctx.get("chat_role")
        if team not in {"team-left", "team-right"}:
            return None

        expires_at = time.time() + self.DISCONNECT_GRACE_SECONDS
        nickname = self.nicknames.get(client_id, "ゲスト")

        reservation = {
            "room_owner_id": ctx.get("room_owner_id"),
            "team": team,
            "expires_at": expires_at,
            "nickname": nickname,
        }
        self.reconnect_reservations[client_id] = reservation
        return reservation

    def _try_restore_participant_reconnect(self, client_id: str):
        self._purge_expired_reconnect_reservations()

        reservation = self.reconnect_reservations.get(client_id)
        if not reservation:
            return None

        room_owner_id = reservation.get("room_owner_id")
        room = self.rooms.get(room_owner_id)
        if room is None:
            self.reconnect_reservations.pop(client_id, None)
            return None

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
        return room_owner_id

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

        recipients = {room_owner_id} | set(room.get("left_participants", set())) | set(room.get("right_participants", set())) | set(room.get("spectators", set()))
        private_map = {target_id: notice_message for target_id in recipients}

        await self.broadcast_state(
            public_info="人数不足によりゲームを終了しました。",
            private_map=private_map,
            event_type="private_notice",
            event_room_id=room_owner_id,
        )
        await self.broadcast_state(
            public_info=f"ゲーム終了！{winner_label}",
            event_type="game_finished",
            event_room_id=room_owner_id,
        )

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

    async def _broadcast_team_log_message(self, owner_id: str, room: dict, event_type: str, message: str):
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
            )

    async def _broadcast_turn_changed_logs(self, owner_id: str, room: dict, message: str):
        await self._broadcast_team_log_message(owner_id, room, "turn_changed", message)

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
            await self.send_private_info(client_id, "進行中の解答送信投票があります。")
            return

        pending_turn_end_vote = room.get("pending_turn_end_vote")
        if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
            await self.send_private_info(client_id, "進行中のターンエンド投票があります。")
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
        should_emit_vote_log = total_voters > 1
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

        event_recipient_ids = voter_ids - {client_id} if total_voters > 1 else voter_ids

        team_label = "先攻" if team == "team-left" else "後攻"
        requester_name = self.nicknames.get(client_id, "ゲスト")
        await self.broadcast_state(
            public_info=f"{team_label}陣営で文字オープン投票を開始しました。",
            event_type="open_vote_request",
            event_message=(f"{requester_name} が {char_index + 1}文字目のオープン投票を開始しました。" if should_emit_vote_log else None),
            event_chat_type=team,
            event_room_id=owner_id,
            event_recipient_ids=event_recipient_ids,
            event_payload={
                "vote_id": vote_id,
                "team": team,
                "char_index": char_index,
                "required_approvals": required_approvals,
                "total_voters": total_voters,
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
        should_emit_vote_log = len(voter_ids) > 1

        team_chat_recipients = set(voter_ids)
        team_chat_result = resolve_chat_recipients(owner_id, room, team, team)
        if team_chat_result.get("ok"):
            team_chat_recipients = team_chat_result["event_recipient_ids"]

        if approvals >= required:
            pending_vote["status"] = "approved"
            previous_turn_team = (room.get("game") or {}).get("current_turn_team")
            result = apply_open_character(room, team, char_index)
            room["pending_open_vote"] = None

            if not result.get("ok"):
                await self.broadcast_state(
                    public_info="文字オープン投票は可決されましたが、オープン処理に失敗しました。",
                    event_type="open_vote_resolved",
                    event_chat_type=team,
                    event_room_id=owner_id,
                    event_payload={
                        "vote_id": vote_id,
                        "approved": False,
                        "char_index": char_index,
                        "reason": result.get("error", "open_failed"),
                    },
                    event_recipient_ids=team_chat_recipients,
                )
                return

            is_yakumono = result.get("is_yakumono", False)
            await self.broadcast_state(
                public_info=f"{char_index + 1}文字目がオープンされました。",
                event_type="open_vote_resolved",
                event_message=(f"オープン投票可決: {char_index + 1}文字目" if should_emit_vote_log else None),
                event_chat_type=team,
                event_room_id=owner_id,
                event_payload={
                    "vote_id": vote_id,
                    "approved": True,
                    "char_index": char_index,
                    "is_yakumono": is_yakumono,
                },
                event_recipient_ids=team_chat_recipients,
            )

            next_turn_team = (room.get("game") or {}).get("current_turn_team")
            should_notify_turn_changed = (room.get("game") or {}).get("game_status") == "playing" and previous_turn_team != next_turn_team
            if should_notify_turn_changed:
                next_label = "先攻" if next_turn_team == "team-left" else "後攻"
                turn_changed_message = f"ターン終了。{next_label}のターンになりました。"
                await self.broadcast_state(
                    public_info=turn_changed_message,
                    event_type="turn_changed",
                    event_room_id=owner_id,
                )
                await self._broadcast_turn_changed_logs(owner_id, room, turn_changed_message)
            return

        max_possible_approvals = approvals + (len(voter_ids) - approvals - rejections)
        if max_possible_approvals < required:
            pending_vote["status"] = "rejected"
            room["pending_open_vote"] = None
            await self.broadcast_state(
                public_info=f"{char_index + 1}文字目のオープン投票は否決されました。",
                event_type="open_vote_resolved",
                event_message=(f"オープン投票否決: {char_index + 1}文字目" if should_emit_vote_log else None),
                event_chat_type=team,
                event_room_id=owner_id,
                event_payload={
                    "vote_id": vote_id,
                    "approved": False,
                    "char_index": char_index,
                    "reason": "rejected",
                },
                event_recipient_ids=team_chat_recipients,
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
            await self.send_private_info(client_id, "進行中の解答送信投票がありません。")
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
        team_label = "先攻" if team == "team-left" else "後攻"
        should_emit_vote_log = len(voter_ids) > 1

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
                    public_info="解答送信投票は可決されましたが、判定待ちの解答があるため送信できませんでした。",
                    event_type="answer_vote_resolved",
                    event_chat_type=team,
                    event_room_id=owner_id,
                    event_recipient_ids=team_chat_recipients,
                    event_payload={
                        "vote_id": vote_id,
                        "approved": False,
                        "reason": "judgement_pending",
                    },
                )
                return

            answer_text = str(pending_vote.get("answer_text", "")).strip()
            requester_id = pending_vote.get("requester_id")
            requester_name = self.nicknames.get(requester_id, "ゲスト")

            game["pending_answer_judgement"] = {
                "team": team,
                "answer_text": answer_text,
                "answerer_id": requester_id,
            }

            await self.broadcast_state(
                public_info=f"{team_label}が解答を提出しました。出題者が正誤判定中です。",
                event_type="answer_attempt",
                event_room_id=owner_id,
            )
            await self._broadcast_team_log_message(
                owner_id,
                room,
                "answer_attempt",
                f"{team_label}が解答を提出しました。",
            )

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

            await self.broadcast_state(
                public_info=f"{team_label}陣営の解答送信投票が可決されました。",
                event_type="answer_vote_resolved",
                event_message=(f"解答送信投票可決: {requester_name}" if should_emit_vote_log else None),
                event_chat_type=team,
                event_room_id=owner_id,
                event_recipient_ids=team_chat_recipients,
                event_payload={
                    "vote_id": vote_id,
                    "approved": True,
                },
            )
            return

        max_possible_approvals = approvals + (len(voter_ids) - approvals - rejections)
        if max_possible_approvals < required:
            pending_vote["status"] = "rejected"
            room["pending_answer_vote"] = None
            await self.broadcast_state(
                public_info=f"{team_label}陣営の解答送信投票は否決されました。",
                event_type="answer_vote_resolved",
                event_message=("解答送信投票否決" if should_emit_vote_log else None),
                event_chat_type=team,
                event_room_id=owner_id,
                event_recipient_ids=team_chat_recipients,
                event_payload={
                    "vote_id": vote_id,
                    "approved": False,
                    "reason": "rejected",
                },
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
            await self.send_private_info(client_id, "解答送信投票中はターンエンドできません。")
            return

        pending_turn_end_vote = room.get("pending_turn_end_vote")
        if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
            await self.send_private_info(client_id, "進行中のターンエンド投票があります。")
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

            next_team = result.get("current_turn_team")
            next_label = "先攻" if next_team == "team-left" else "後攻"
            await self.broadcast_state(
                public_info=f"ターン終了。{next_label}のターンになりました。",
                event_type="turn_changed",
                event_room_id=owner_id,
            )
            await self._broadcast_turn_changed_logs(
                owner_id,
                room,
                f"ターン終了。{next_label}のターンになりました。",
            )
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

        team_label = "先攻" if team == "team-left" else "後攻"
        requester_name = self.nicknames.get(client_id, "ゲスト")
        await self.broadcast_state(
            public_info=f"{team_label}陣営でターンエンド投票を開始しました。",
            event_type="turn_end_vote_request",
            event_message=f"{requester_name} がターンエンド投票を開始しました。",
            event_chat_type=team,
            event_room_id=owner_id,
            event_recipient_ids=voter_ids - {client_id},
            event_payload={
                "vote_id": vote_id,
                "team": team,
                "team_label": team_label,
                "required_approvals": required_approvals,
                "total_voters": total_voters,
            },
        )

        await self.send_private_info(client_id, "提案しました。")

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
        team_label = "先攻" if team == "team-left" else "後攻"

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
                    public_info="ターンエンド投票は可決されましたが、ターン終了処理に失敗しました。",
                    event_type="turn_end_vote_resolved",
                    event_chat_type=team,
                    event_room_id=owner_id,
                    event_recipient_ids=team_chat_recipients,
                    event_payload={
                        "vote_id": vote_id,
                        "approved": False,
                        "reason": result.get("error", "end_turn_failed"),
                    },
                )
                return

            await self.broadcast_state(
                public_info=f"{team_label}陣営のターンエンド投票が可決されました。",
                event_type="turn_end_vote_resolved",
                event_message="ターンエンド投票可決",
                event_chat_type=team,
                event_room_id=owner_id,
                event_recipient_ids=team_chat_recipients,
                event_payload={
                    "vote_id": vote_id,
                    "approved": True,
                },
            )

            next_team = result.get("current_turn_team")
            next_label = "先攻" if next_team == "team-left" else "後攻"
            await self.broadcast_state(
                public_info=f"ターン終了。{next_label}のターンになりました。",
                event_type="turn_changed",
                event_room_id=owner_id,
            )
            await self._broadcast_turn_changed_logs(
                owner_id,
                room,
                f"ターン終了。{next_label}のターンになりました。",
            )
            return

        max_possible_approvals = approvals + (len(voter_ids) - approvals - rejections)
        if max_possible_approvals < required:
            pending_vote["status"] = "rejected"
            room["pending_turn_end_vote"] = None
            await self.broadcast_state(
                public_info=f"{team_label}陣営のターンエンド投票は否決されました。",
                event_type="turn_end_vote_resolved",
                event_message="ターンエンド投票否決",
                event_chat_type=team,
                event_room_id=owner_id,
                event_recipient_ids=team_chat_recipients,
                event_payload={
                    "vote_id": vote_id,
                    "approved": False,
                    "reason": "rejected",
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
        self.rooms.pop(room_owner_id, None)
        self._clear_room_reconnect_reservations(room_owner_id)

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

        role_name = result.get("event_role_name")
        if role_name is None:
            return

        room = self.rooms.get(room_owner_id)
        if room is None:
            return

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
            room["pre_game_global_chat_history"] = []
            room["pre_game_global_chat_seq"] = 0

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

        questioner_name = result["questioner_name"]
        await self.broadcast_state(
            public_info=f"{questioner_name} が参加者をシャッフルしました",
            event_type="room_shuffle",
            event_message=f"{questioner_name} が参加者をシャッフルしました",
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
        """解答を提出するアクション"""
        ctx = resolve_client_room_context(self.rooms, client_id)
        if ctx is None:
            await self.send_private_info(client_id, "ゲーム部屋に参加していません。")
            return

        room = ctx["room"]
        owner_id = ctx["room_owner_id"]

        # 出題者のみが正誤を判定できる
        if ctx["role"] != "owner":
            await self.send_private_info(client_id, "解答の正誤判定は出題者のみ実行できます。")
            return

        result = apply_submit_answer(room, room["game"]["current_turn_team"], is_correct)
        if not result.get("ok"):
            await self.send_private_info(client_id, result.get("error", "解答の提出に失敗しました。"))
            return

        current_team_name = room["game"]["current_turn_team"]
        team_label = "先攻" if current_team_name == "team-left" else "後攻"
        status_text = "正解！" if is_correct else "誤答。"

        await self.broadcast_state(
            public_info=f"{team_label}が解答を提出しました。{status_text}",
            event_type="answer_submitted",
            event_room_id=owner_id,
        )

        # ゲーム終了判定
        if result.get("game_status") == "finished":
            winner = result.get("winner")
            winner_label = "先攻" if winner == "team-left" else "後攻"
            await self.broadcast_state(
                public_info=f"ゲーム終了！{winner_label}が勝利しました！",
                event_type="game_finished",
                event_room_id=owner_id,
            )

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
            await self.send_private_info(client_id, "対戦中のみ解答できます。")
            return

        game = room.get("game") or {}
        if game.get("pending_answer_judgement") is not None:
            await self.send_private_info(client_id, "現在、別の解答を正誤判定中です。")
            return

        pending_answer_vote = room.get("pending_answer_vote")
        if pending_answer_vote and pending_answer_vote.get("status") == "pending":
            await self.send_private_info(client_id, "現在、別の解答送信投票が進行中です。")
            return

        pending_turn_end_vote = room.get("pending_turn_end_vote")
        if pending_turn_end_vote and pending_turn_end_vote.get("status") == "pending":
            await self.send_private_info(client_id, "ターンエンド投票中は解答を送信できません。")
            return

        pending_open_vote = room.get("pending_open_vote")
        if pending_open_vote and pending_open_vote.get("status") == "pending":
            await self.send_private_info(client_id, "文字オープン投票中は解答を送信できません。")
            return

        if client_id in room["left_participants"]:
            team = "team-left"
            team_label = "先攻"
        elif client_id in room["right_participants"]:
            team = "team-right"
            team_label = "後攻"
        else:
            await self.send_private_info(client_id, "参加者のみ解答できます。")
            return

        if game.get("current_turn_team") != team:
            await self.send_private_info(client_id, "自分のターンでのみ解答できます。")
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
            game["pending_answer_judgement"] = {
                "team": team,
                "answer_text": text,
                "answerer_id": client_id,
            }

            await self.broadcast_state(
                public_info=f"{team_label}が解答を提出しました。出題者が正誤判定中です。",
                event_type="answer_attempt",
                event_room_id=owner_id,
            )
            await self._broadcast_team_log_message(
                owner_id,
                room,
                "answer_attempt",
                f"{team_label}が解答を提出しました。",
            )

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

            await self.send_private_info(client_id, "送信しました。")
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
            public_info=f"{team_label}陣営で解答送信投票を開始しました。",
            event_type="answer_vote_request",
            event_message=(f"{nickname} が解答送信投票を開始しました。" if should_emit_vote_log else None),
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
        previous_turn_team = game.get("current_turn_team")
        game["pending_answer_judgement"] = None
        result = apply_submit_answer(room, team, is_correct)

        if not result.get("ok"):
            await self.send_private_info(client_id, result.get("error", "正誤判定に失敗しました。"))
            return

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
            # Check if game finished due to wrong answer after left team answered correctly
            if result.get("game_status") == "finished" and result.get("winner") == "team-left":
                # Right team failed to answer correctly after left answered correctly
                end_msg = "後攻が正解できませんでした。先攻の勝利です。"
                for target_id in left_ids | right_ids | spectator_ids | questioner_ids:
                    private_map[target_id] = end_msg
            else:
                # Normal wrong answer case
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

                for target_id in spectator_ids | questioner_ids:
                    private_map[target_id] = "正誤判定が完了しました。"

        await self.broadcast_state(
            public_info="正誤判定が完了しました。",
            private_map=private_map,
            event_type="private_notice",
            event_room_id=owner_id,
        )

        team_label = "先攻" if team == "team-left" else "後攻"
        result_label = "正解" if is_correct else "誤答"
        await self._broadcast_team_log_message(
            owner_id,
            room,
            "answer_result",
            f"{team_label}の解答は{result_label}でした。",
        )

        next_turn_team = (room.get("game") or {}).get("current_turn_team")
        should_notify_turn_changed = result.get("game_status") == "playing" and previous_turn_team != next_turn_team
        if should_notify_turn_changed:
            next_label = "先攻" if next_turn_team == "team-left" else "後攻"
            turn_changed_message = f"ターン終了。{next_label}のターンになりました。"
            await self.broadcast_state(
                public_info=turn_changed_message,
                event_type="turn_changed",
                event_room_id=owner_id,
            )
            await self._broadcast_turn_changed_logs(owner_id, room, turn_changed_message)

        # Only send game_finished event if not already handled by private_notice
        if result.get("game_status") == "finished":
            # If right team failed after left answered correctly, already handled in private_notice
            if result.get("winner") == "team-left" and team == "team-right" and not is_correct:
                pass  # Already shown in private_notice, no need for separate game_finished event
            else:
                winner = result.get("winner")
                if winner == "team-left":
                    winner_label = "先攻"
                elif winner == "team-right":
                    winner_label = "後攻"
                else:
                    winner_label = "引き分け"

                await self.broadcast_state(
                    public_info=f"ゲーム終了！{winner_label}",
                    event_type="game_finished",
                    event_room_id=owner_id,
                )

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
        restored_room_owner_id = self._try_restore_participant_reconnect(client_id)
        self._clear_pending_disconnect_everywhere(client_id)
        self._cancel_disconnect_grace_timer(client_id)
        print(f"プレイヤー接続: {nickname} ({client_id}) (現在: {len(self.active_connections)}人)")

        await self.broadcast_state(
            public_info=f"{nickname} が参加しました",
            private_map={client_id: "QuizOpenBattleへようこそ"},
            event_type="join",
            event_message=f"{nickname} が入場しました",
        )

        if restored_room_owner_id:
            await self.send_private_info(
                client_id,
                "再接続して部屋に復帰しました。",
                target_screen="game_arena",
                event_type="room_reconnected",
            )
        return True

    async def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            ctx_before_disconnect = resolve_client_room_context(self.rooms, client_id)
            reservation = self._reserve_participant_reconnect(client_id, ctx_before_disconnect)

            del self.active_connections[client_id]
            nickname = self.nicknames.pop(client_id, client_id)
            self.chat_message_history.pop(client_id, None)
            self.chat_last_message.pop(client_id, None)

            closed_room = self.rooms.pop(client_id, None)
            is_grace_disconnect = reservation is not None and closed_room is None
            if not is_grace_disconnect:
                remove_client_from_all_rooms_logic(self.rooms, client_id)

            if is_grace_disconnect and reservation is not None:
                room_owner_id = reservation.get("room_owner_id")
                team = reservation.get("team")
                expires_at = float(reservation.get("expires_at") or 0)
                if room_owner_id and team in {"team-left", "team-right"} and expires_at > time.time():
                    self._set_room_pending_disconnect(room_owner_id, client_id, nickname, team, expires_at)
                    self._schedule_participant_disconnect_grace(client_id, room_owner_id, expires_at, nickname)

                    remaining_seconds = max(1, int(expires_at - time.time()))
                    team_label = "先攻" if team == "team-left" else "後攻"
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

            if closed_room is not None:
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
        result = apply_create_question_room(self.rooms, self.nicknames, player_id, payload)
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
            event_message=f"{actor_name} が 出題をしました",
            event_room_id=player_id,
        )

        # 出題者自身も部屋作成直後にゲーム会場へ遷移させる。
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
            pre_history = room.setdefault("pre_game_global_chat_history", [])
            if not isinstance(pre_history, list):
                pre_history = []
                room["pre_game_global_chat_history"] = pre_history
            pre_history.append(
                {
                    "seq": pre_seq,
                    "timestamp": int(time.time() * 1000),
                    "event_type": "chat",
                    "event_message": f"{nickname}: {message}",
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
                # 【対策2】受信したデータが正しいJSONかチェックする
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

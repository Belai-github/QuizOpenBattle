from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import json
import time

from backend.game_logic import (
    apply_create_question_room,
    apply_exit_room,
    apply_join_room,
    apply_shuffle_participants,
    apply_start_game,
    build_current_room_for_client,
    remove_client_from_all_rooms as remove_client_from_all_rooms_logic,
    resolve_chat_recipients,
    resolve_client_room_context,
)

app = FastAPI()

app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")


class QuizGameManager:
    def __init__(self):
        self.active_connections = {}
        self.nicknames = {}
        self.rooms = {}
        # 【対策1】同時に接続できる最大人数を設定
        self.MAX_CONNECTIONS = 4
        self.CHAT_MAX_LENGTH = 200
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
    ):
        participants = self.build_participants()
        for client_id, ws in self.active_connections.items():
            rooms = self.build_rooms_summary(client_id)
            current_room = self.build_current_room_for_client(client_id)
            private_info = ""
            if private_map is not None:
                private_info = private_map.get(client_id, "")

            is_event_recipient = event_recipient_ids is None or client_id in event_recipient_ids
            response_event_type = event_type if is_event_recipient else None
            response_event_message = event_message if is_event_recipient else None
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
            }
            await ws.send_text(json.dumps(response))

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

    async def start_game(self, client_id: str):
        result = apply_start_game(self.rooms, client_id)
        if not result.get("ok"):
            await self.send_private_info(client_id, result.get("error", "ゲーム開始に失敗しました。"))
            return

        questioner_name = result["questioner_name"]
        await self.broadcast_state(
            public_info=f"{questioner_name} がゲームを開始しました",
            event_type="game_start",
            event_message=f"{questioner_name} がゲームを開始しました",
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

    async def connect(self, websocket: WebSocket, client_id: str, nickname: str):
        await websocket.accept()

        # 接続上限に達している場合は、即座に通信を切断する
        if len(self.active_connections) >= self.MAX_CONNECTIONS:
            # WebSocketのステータスコード1008は「ポリシー違反（リソース超過など）」を意味します
            await websocket.close(code=1008, reason="Server is full or Rate limited")
            print(f"接続拒否（満員）: {client_id}")
            return False

        self.active_connections[client_id] = websocket
        self.nicknames[client_id] = nickname
        print(f"プレイヤー接続: {nickname} ({client_id}) (現在: {len(self.active_connections)}人)")

        await self.broadcast_state(
            public_info=f"{nickname} が参加しました",
            private_map={client_id: "QuizOpenBattleへようこそ"},
            event_type="join",
            event_message=f"{nickname} が入室しました",
        )
        return True

    async def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            nickname = self.nicknames.pop(client_id, client_id)
            self.chat_message_history.pop(client_id, None)
            self.chat_last_message.pop(client_id, None)

            closed_room = self.rooms.pop(client_id, None)
            remove_client_from_all_rooms_logic(self.rooms, client_id)

            if closed_room is not None:
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
                public_info=f"{nickname} が退出しました",
                event_type="leave",
                event_message=f"{nickname} が退室しました",
            )

            if closed_room is not None:
                await self.broadcast_state(
                    public_info=f"{nickname} の部屋が閉じられました",
                    event_type="room_closed",
                    event_message=f"{nickname} の出題部屋が閉じられました",
                    event_room_id=client_id,
                )

    async def exit_room(self, client_id: str):
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
        )

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
            await self.start_game(client_id)
            return

        if payload_type == "shuffle_participants":
            await self.shuffle_participants(client_id)
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


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    nickname = websocket.query_params.get("nickname", "ゲスト").strip()
    if nickname == "":
        nickname = "ゲスト"

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

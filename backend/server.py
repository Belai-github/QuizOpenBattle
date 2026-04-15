from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import json
import random
import time

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
                    "is_owner": viewer_client_id == owner_id,
                }
            )
        return rooms

    def build_current_room_for_client(self, client_id: str):
        for owner_id, room in self.rooms.items():
            if owner_id == client_id:
                role = "owner"
                chat_role = "questioner"
            elif client_id in room["left_participants"] or client_id in room["right_participants"]:
                role = "participant"
                if client_id in room["left_participants"]:
                    chat_role = "team-left"
                else:
                    chat_role = "team-right"
            elif client_id in room["spectators"]:
                role = "spectator"
                chat_role = "spectator"
            else:
                continue

            # 左右の参加者を別々にリスト化
            left_participant_names = []
            for pid in room["left_participants"]:
                left_participant_names.append(self.nicknames.get(pid, "ゲスト"))

            right_participant_names = []
            for pid in room["right_participants"]:
                right_participant_names.append(self.nicknames.get(pid, "ゲスト"))

            spectator_names = []
            for sid in room["spectators"]:
                spectator_names.append(self.nicknames.get(sid, "ゲスト"))

            return {
                "room_owner_id": owner_id,
                "questioner_name": room["questioner_name"],
                "question_text": room["question_text"],
                "role": role,
                "chat_role": chat_role,
                "left_participants": left_participant_names,
                "right_participants": right_participant_names,
                "spectators": spectator_names,
            }

        return None

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
        for room in self.rooms.values():
            room["left_participants"].discard(client_id)
            room["right_participants"].discard(client_id)
            room["spectators"].discard(client_id)

    async def join_room(self, client_id: str, room_owner_id: str, role: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            await self.send_private_info(client_id, "部屋が見つかりません。")
            return

        if client_id == room_owner_id:
            await self.send_private_info(client_id, "あなたの出題部屋に入室しました。", target_screen="game_arena")
            return

        self.remove_client_from_all_rooms(client_id)

        if role == "participant":
            # 左右の参加者数を比較して配置を決定
            left_count = len(room["left_participants"])
            right_count = len(room["right_participants"])

            if left_count == right_count:
                # 同数の場合はランダム
                side = random.choice(["left", "right"])
            elif left_count < right_count:
                # 左の方が少ない場合は左へ
                side = "left"
            else:
                # 右の方が少ない場合は右へ
                side = "right"

            if side == "left":
                room["left_participants"].add(client_id)
            else:
                room["right_participants"].add(client_id)

            role_name = "参加者"
        else:
            room["spectators"].add(client_id)
            role_name = "観戦者"

        nickname = self.nicknames.get(client_id, "ゲスト")
        await self.send_private_info(
            client_id,
            f"{room['questioner_name']} の部屋に{role_name}として入りました。",
            target_screen="game_arena",
        )

        await self.broadcast_state(
            public_info=f"{nickname} が部屋に入りました",
            event_type="room_entry",
            event_message=f"{nickname} が {room['questioner_name']} の部屋に{role_name}として参加しました",
            event_room_id=room_owner_id,
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
            self.remove_client_from_all_rooms(client_id)

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

        # 出題者が退室した場合は、その出題部屋を閉じる。
        if client_id in self.rooms:
            room = self.rooms.pop(client_id)

            affected_client_ids = set(room["left_participants"]) | set(room["right_participants"]) | set(room["spectators"])
            for target_client_id in affected_client_ids:
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

        self.remove_client_from_all_rooms(client_id)
        await self.broadcast_state(
            public_info=f"{nickname} が部屋から退室しました",
            event_type="room_exit",
            event_message=f"{nickname} が部屋から退室しました",
        )

    async def process_question(self, player_id: str, payload: dict):
        if player_id in self.rooms:
            await self.send_private_info(player_id, "同時に出題できる問題は1つまでです。")
            return

        private_map = {}
        actor_name = self.nicknames.get(player_id, "相手")
        question_text = str(payload.get("question_text", payload.get("content", ""))).strip()
        if question_text == "":
            question_text = "（空欄）"

        self.rooms[player_id] = {
            "owner_id": player_id,
            "question_text": question_text,
            "questioner_name": actor_name,
            "left_participants": set(),
            "right_participants": set(),
            "spectators": set(),
        }

        # 出題者は作成時点で自分の部屋に所属する。
        self.remove_client_from_all_rooms(player_id)

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

        current_room = self.build_current_room_for_client(client_id)
        if current_room is None:
            await self.send_private_info(client_id, "部屋に参加していないため、部屋内チャットは送信できません。")
            return

        room_owner_id = current_room.get("room_owner_id")
        room = self.rooms.get(room_owner_id)
        if room is None:
            await self.send_private_info(client_id, "部屋情報の取得に失敗しました。")
            return

        sender_chat_role = current_room.get("chat_role")
        sendable_roles_by_type = {
            "team-left": {"team-left", "questioner"},
            "team-right": {"team-right", "questioner"},
            "spectator": {"spectator", "questioner"},
        }
        readable_roles_by_type = {
            "team-left": {"team-left", "questioner", "spectator"},
            "team-right": {"team-right", "questioner", "spectator"},
            "spectator": {"spectator", "questioner"},
        }

        if chat_type not in sendable_roles_by_type:
            await self.send_private_info(client_id, "未対応のチャット種別です。")
            return

        if sender_chat_role not in sendable_roles_by_type[chat_type]:
            await self.send_private_info(client_id, "このチャット欄では発言できません。")
            return

        role_to_ids = {
            "questioner": {room_owner_id},
            "team-left": set(room["left_participants"]),
            "team-right": set(room["right_participants"]),
            "spectator": set(room["spectators"]),
        }
        event_recipient_ids = set()
        for role_name in readable_roles_by_type[chat_type]:
            event_recipient_ids |= role_to_ids.get(role_name, set())

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

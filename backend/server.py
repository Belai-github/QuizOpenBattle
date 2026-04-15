from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import json

app = FastAPI()

app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")


class QuizGameManager:
    def __init__(self):
        self.active_connections = {}
        self.nicknames = {}
        self.rooms = {}
        # 【対策1】同時に接続できる最大人数を設定
        self.MAX_CONNECTIONS = 4

    def build_participants(self):
        participants = []
        for client_id, nickname in self.nicknames.items():
            participants.append({"client_id": client_id, "nickname": nickname})
        return participants

    def build_rooms_summary(self, viewer_client_id: str | None = None):
        rooms = []
        for owner_id, room in self.rooms.items():
            rooms.append(
                {
                    "room_owner_id": owner_id,
                    "questioner_name": room["questioner_name"],
                    "question_text": room["question_text"],
                    "participant_count": len(room["participants"]),
                    "spectator_count": len(room["spectators"]),
                    "is_owner": viewer_client_id == owner_id,
                }
            )
        return rooms

    async def broadcast_state(
        self,
        public_info: str,
        private_map: dict | None = None,
        event_type: str | None = None,
        event_message: str | None = None,
        event_room_id: str | None = None,
        target_screen: str | None = None,
    ):
        participants = self.build_participants()
        for client_id, ws in self.active_connections.items():
            rooms = self.build_rooms_summary(client_id)
            private_info = ""
            if private_map is not None:
                private_info = private_map.get(client_id, "")

            response = {
                "public_info": public_info,
                "private_info": private_info,
                "participants": participants,
                "rooms": rooms,
                "event_type": event_type,
                "event_message": event_message,
                "event_room_id": event_room_id,
                "target_screen": target_screen,
            }
            await ws.send_text(json.dumps(response))

    async def send_private_info(self, client_id: str, message: str, target_screen: str | None = None):
        ws = self.active_connections.get(client_id)
        if ws is None:
            return

        response = {
            "public_info": "",
            "private_info": message,
            "participants": self.build_participants(),
            "rooms": self.build_rooms_summary(client_id),
            "event_type": "private_notice",
            "event_message": None,
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
        self.rooms.pop(room_owner_id, None)

        await self.broadcast_state(
            public_info=f"{questioner_name} の出題が取り消されました",
            event_type="room_closed",
            event_message=f"{questioner_name} が出題を取り消しました",
            event_room_id=room_owner_id,
        )

    def remove_client_from_all_rooms(self, client_id: str):
        for room in self.rooms.values():
            room["participants"].discard(client_id)
            room["spectators"].discard(client_id)

    async def join_room(self, client_id: str, room_owner_id: str, role: str):
        room = self.rooms.get(room_owner_id)
        if room is None:
            await self.send_private_info(client_id, "部屋が見つかりません。")
            return

        if client_id == room_owner_id:
            await self.send_private_info(client_id, "あなたはこの部屋の出題者です。")
            return

        self.remove_client_from_all_rooms(client_id)

        if role == "participant":
            room["participants"].add(client_id)
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

            closed_room = self.rooms.pop(client_id, None)
            self.remove_client_from_all_rooms(client_id)

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
            "participants": set(),
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

    async def process_client_payload(self, client_id: str, payload: dict):
        payload_type = payload.get("type")

        if payload_type == "question_submission":
            await self.process_question(client_id, payload)
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

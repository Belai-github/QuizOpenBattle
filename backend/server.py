from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import json

app = FastAPI()

app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")


class QuizGameManager:
    def __init__(self):
        self.active_connections = {}
        self.nicknames = {}
        # 【対策1】同時に接続できる最大人数を設定（例: プレイヤー2人＋観戦2人 = 4）
        self.MAX_CONNECTIONS = 4

    def build_participants(self):
        participants = []
        for client_id, nickname in self.nicknames.items():
            participants.append({"client_id": client_id, "nickname": nickname})
        return participants

    async def broadcast_state(self, public_info: str, private_map: dict | None = None):
        participants = self.build_participants()
        for client_id, ws in self.active_connections.items():
            private_info = ""
            if private_map is not None:
                private_info = private_map.get(client_id, "")

            response = {
                "public_info": public_info,
                "private_info": private_info,
                "participants": participants,
            }
            await ws.send_text(json.dumps(response))

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
            private_map={client_id: "ゲームへようこそ"},
        )
        return True

    async def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            nickname = self.nicknames.pop(client_id, client_id)
            print(f"プレイヤー切断: {nickname} ({client_id}) (現在: {len(self.active_connections)}人)")
            await self.broadcast_state(public_info=f"{nickname} が退出しました")

    async def process_action(self, action_player_id: str, action_data: dict):
        private_map = {}
        actor_name = self.nicknames.get(action_player_id, "相手")
        for client_id in self.active_connections.keys():
            if client_id == action_player_id:
                private_map[client_id] = f"あなたは「{action_data.get('action')}」を選択しました。"
            else:
                private_map[client_id] = f"{actor_name} が行動を完了しました。あなたのターンです。"

        await self.broadcast_state(public_info="行動が受理されました", private_map=private_map)


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
                action_data = json.loads(data)
                await manager.process_action(client_id, action_data)

            except json.JSONDecodeError:
                # 不正な文字列スパムが送られてきた場合、エラーでサーバーを落とさずに「無視」する
                print(f"警告: {client_id} から不正なデータを受信しました")
                pass

    except WebSocketDisconnect:
        await manager.disconnect(client_id)

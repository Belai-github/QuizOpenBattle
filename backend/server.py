from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import json

app = FastAPI()

app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")


class QuizGameManager:
    def __init__(self):
        self.active_connections = {}
        # 【対策1】同時に接続できる最大人数を設定（例: プレイヤー2人＋観戦2人 = 4）
        self.MAX_CONNECTIONS = 4

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()

        # 接続上限に達している場合は、即座に通信を切断する
        if len(self.active_connections) >= self.MAX_CONNECTIONS:
            # WebSocketのステータスコード1008は「ポリシー違反（リソース超過など）」を意味します
            await websocket.close(code=1008, reason="Server is full or Rate limited")
            print(f"接続拒否（満員）: {client_id}")
            return False

        self.active_connections[client_id] = websocket
        print(f"プレイヤー接続: {client_id} (現在: {len(self.active_connections)}人)")
        return True

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            print(f"プレイヤー切断: {client_id} (現在: {len(self.active_connections)}人)")

    async def process_action(self, action_player_id: str, action_data: dict):
        # （前回の処理と同じ）
        for client_id, ws in self.active_connections.items():
            if client_id == action_player_id:
                secret_msg = f"あなたは「{action_data.get('action')}」を選択しました。"
            else:
                secret_msg = "相手が行動を完了しました。あなたのターンです。"

            response = {"public_info": "行動が受理されました", "private_info": secret_msg}
            await ws.send_text(json.dumps(response))


manager = QuizGameManager()


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    # 接続処理を行い、許可されなかった（False）場合はここで処理を終える
    is_accepted = await manager.connect(websocket, client_id)
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
        manager.disconnect(client_id)

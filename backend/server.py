from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import json

app = FastAPI()

# 開発テスト用に、http://localhost:8000/ で frontend フォルダの中身を配信する設定
app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")


class QuizGameManager:
    def __init__(self):
        # 接続中のプレイヤーを管理 (client_id -> WebSocket)
        self.active_connections = {}
        self.turn = 1

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        print(f"プレイヤー接続: {client_id}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            print(f"プレイヤー切断: {client_id}")

    async def process_action(self, action_player_id: str, action_data: dict):
        """プレイヤーからの行動を受け取り、状態を更新して全員に結果を返す"""
        self.turn += 1

        # 将来的にはここで game_logic.py の関数を呼び出し、盤面を計算します

        # 全プレイヤーに状態を送信（非対称情報のテスト）
        for client_id, ws in self.active_connections.items():
            # プレイヤーごとに見える情報を変える
            if client_id == action_player_id:
                secret_msg = f"あなたは「{action_data.get('action')}」を選択しました。"
            else:
                secret_msg = "相手が行動を完了しました。あなたのターンです。"

            response = {"turn": self.turn, "public_info": f"現在のターン: {self.turn}", "private_info": secret_msg}
            await ws.send_text(json.dumps(response))


manager = QuizGameManager()


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            # クライアントからのメッセージを受信
            data = await websocket.receive_text()
            action_data = json.loads(data)
            await manager.process_action(client_id, action_data)
    except WebSocketDisconnect:
        manager.disconnect(client_id)

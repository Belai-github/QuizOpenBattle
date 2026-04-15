from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import json
import time

app = FastAPI()

app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")


class QuizGameManager:
    def __init__(self):
        self.active_connections = {}
        self.nicknames = {}  # client_id -> nickname
        self.nickname_cache = {}  # client_id -> {"nickname": str, "expires_at": float}

        self.MAX_CONNECTIONS = 4
        self.NICKNAME_TTL_SEC = 60 * 60 * 24 * 7  # 7日

    def _cleanup_cache(self):
        now = time.time()
        expired_ids = [cid for cid, v in self.nickname_cache.items() if v.get("expires_at", 0) < now]
        for cid in expired_ids:
            del self.nickname_cache[cid]

    async def _broadcast_participants(self):
        participants = []
        for cid in self.active_connections.keys():
            participants.append({"client_id": cid, "nickname": self.nicknames.get(cid, cid)})

        payload = json.dumps({"type": "participants", "participants": participants})

        stale = []
        for cid, ws in self.active_connections.items():
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(cid)

        for cid in stale:
            self.active_connections.pop(cid, None)
            self.nicknames.pop(cid, None)

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()

        # 同じclient_idで再接続した場合は古い接続を閉じる
        old_ws = self.active_connections.get(client_id)
        if old_ws is not None:
            try:
                await old_ws.close(code=1000, reason="Reconnected")
            except Exception:
                pass

        # 新規IDのときだけ上限チェック
        if old_ws is None and len(self.active_connections) >= self.MAX_CONNECTIONS:
            await websocket.close(code=1008, reason="Server is full or Rate limited")
            print(f"接続拒否（満員）: {client_id}")
            return False

        self.active_connections[client_id] = websocket
        self._cleanup_cache()

        # キャッシュからニックネーム復元
        cached = self.nickname_cache.get(client_id)
        if cached and cached.get("expires_at", 0) >= time.time():
            self.nicknames[client_id] = cached.get("nickname", client_id)

        print(f"プレイヤー接続: {client_id} (現在: {len(self.active_connections)}人)")
        await self._broadcast_participants()
        return True

    async def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)

        # 切断時もキャッシュに保存しておく
        nickname = self.nicknames.pop(client_id, None)
        if nickname:
            self.nickname_cache[client_id] = {"nickname": nickname, "expires_at": time.time() + self.NICKNAME_TTL_SEC}

        print(f"プレイヤー切断: {client_id} (現在: {len(self.active_connections)}人)")
        await self._broadcast_participants()

    async def set_nickname(self, client_id: str, nickname: str):
        nickname = (nickname or "").strip()[:20]
        if not nickname:
            return

        self.nicknames[client_id] = nickname
        self.nickname_cache[client_id] = {"nickname": nickname, "expires_at": time.time() + self.NICKNAME_TTL_SEC}
        await self._broadcast_participants()

    async def process_action(self, action_player_id: str, action_data: dict):
        actor_name = self.nicknames.get(action_player_id, action_player_id)

        for client_id, ws in self.active_connections.items():
            if client_id == action_player_id:
                secret_msg = f"あなたは「{action_data.get('action')}」を選択しました。"
            else:
                secret_msg = f"{actor_name} が行動を完了しました。あなたのターンです。"

            response = {"type": "action_result", "public_info": "行動が受理されました", "private_info": secret_msg}
            await ws.send_text(json.dumps(response))


manager = QuizGameManager()


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    is_accepted = await manager.connect(websocket, client_id)
    if not is_accepted:
        return

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                print(f"警告: {client_id} から不正なデータを受信しました")
                continue

            msg_type = payload.get("type", "action")
            if msg_type == "set_nickname":
                await manager.set_nickname(client_id, payload.get("nickname", ""))
            elif msg_type == "get_participants":
                await manager._broadcast_participants()
            else:
                await manager.process_action(client_id, payload)

    except WebSocketDisconnect:
        await manager.disconnect(client_id)

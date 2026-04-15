from typing import Any

from fastapi import HTTPException, Query
from pydantic import BaseModel

from backend.auth import is_valid_client_id, sanitize_nickname
from backend.storage.kifu_storage import get_kifu_detail_for_client, list_kifu_for_client
from backend.model_catalog import get_frontend_model_payload


class WsTicketIssueRequest(BaseModel):
    client_id: str
    nickname: str


def register_api_routes(app, manager: Any, ws_auth_manager: Any, diag_api_log):
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

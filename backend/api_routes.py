from typing import Any

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel

from backend.account_auth import AccountAuthManager, sanitize_account_name
from backend.auth import is_valid_client_id, sanitize_guest_nickname
from backend.model_catalog import get_frontend_model_payload
from backend.storage.kifu_storage import get_kifu_detail_for_identity, list_kifu_for_identity


class PasskeyRegisterStartRequest(BaseModel):
    display_name: str


class PasskeyCeremonyFinishRequest(BaseModel):
    ceremony_id: str
    credential: dict[str, Any]
    client_id: str | None = None


class ClientLinkRequest(BaseModel):
    client_id: str


class WsTicketIssueRequest(BaseModel):
    client_id: str


class GuestWsTicketIssueRequest(BaseModel):
    client_id: str
    nickname: str | None = None


def register_api_routes(app, manager: Any, ws_auth_manager: Any, account_auth_manager: AccountAuthManager, diag_api_log):
    def _resolve_current_user_or_401(request: Request):
        user = account_auth_manager.get_authenticated_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="not_authenticated")
        return user

    @app.get("/api/me")
    async def get_me(request: Request):
        user = account_auth_manager.get_authenticated_user(request)
        if user is None:
            return {
                "authenticated": False,
                "webauthn_ready": account_auth_manager.is_webauthn_available(),
            }
        return {
            "authenticated": True,
            "webauthn_ready": account_auth_manager.is_webauthn_available(),
            "user": {
                "user_id": user.user_id,
                "display_name": user.display_name,
                "stats": dict(user.stats),
                "linked_client_ids": list(user.linked_client_ids),
                "current_client_id": user.current_client_id,
            },
        }

    @app.post("/api/auth/register/start")
    async def start_passkey_registration(request: Request, payload: PasskeyRegisterStartRequest):
        display_name = sanitize_account_name(payload.display_name)
        if display_name == "":
            raise HTTPException(status_code=400, detail="empty_display_name")
        return account_auth_manager.begin_registration(display_name, request)

    @app.post("/api/auth/register/finish")
    async def finish_passkey_registration(request: Request, response: Response, payload: PasskeyCeremonyFinishRequest):
        user_payload = account_auth_manager.finish_registration(
            payload.ceremony_id,
            payload.credential,
            request,
            response,
            payload.client_id,
        )
        return {"authenticated": True, "user": user_payload}

    @app.post("/api/auth/login/start")
    async def start_passkey_login(request: Request):
        return account_auth_manager.begin_authentication(request)

    @app.post("/api/auth/login/finish")
    async def finish_passkey_login(request: Request, response: Response, payload: PasskeyCeremonyFinishRequest):
        user_payload = account_auth_manager.finish_authentication(
            payload.ceremony_id,
            payload.credential,
            request,
            response,
            payload.client_id,
        )
        return {"authenticated": True, "user": user_payload}

    @app.post("/api/auth/logout")
    async def logout(request: Request, response: Response):
        account_auth_manager.logout(request, response)
        return {"ok": True}

    @app.post("/api/auth/link-client")
    async def link_client(request: Request, payload: ClientLinkRequest):
        user = account_auth_manager.ensure_linked_client_for_request(request, payload.client_id)
        return {
            "linked_client_ids": list(user.linked_client_ids),
            "current_client_id": user.current_client_id,
        }

    @app.get("/api/kifu/list")
    async def kifu_list(request: Request):
        user = _resolve_current_user_or_401(request)
        diag_api_log(
            "auth_check",
            path="kifu_list",
            user_id=user.user_id,
            linked_client_ids=len(user.linked_client_ids),
            status=200,
        )
        return {"kifu": list_kifu_for_identity(user.user_id, user.linked_client_ids)}

    @app.get("/api/kifu/{kifu_id}")
    async def kifu_detail(kifu_id: str, request: Request):
        user = _resolve_current_user_or_401(request)
        diag_api_log(
            "auth_check",
            path="kifu_detail",
            user_id=user.user_id,
            linked_client_ids=len(user.linked_client_ids),
            status=200,
        )
        detail = get_kifu_detail_for_identity(kifu_id, user.user_id, user.linked_client_ids)
        if detail is None:
            raise HTTPException(status_code=404, detail="kifu_not_found")
        if detail == {}:
            raise HTTPException(status_code=403, detail="forbidden")
        return detail

    @app.get("/api/profile/{client_id}")
    async def get_public_profile(client_id: str):
        resolved_client_id = str(client_id or "").strip()
        if not is_valid_client_id(resolved_client_id):
            raise HTTPException(status_code=400, detail="invalid_client_id")

        nickname = str(manager.nicknames.get(resolved_client_id) or "").strip()
        if nickname == "":
            raise HTTPException(status_code=404, detail="profile_not_found")

        user_id = str(manager.client_user_ids.get(resolved_client_id) or "").strip()
        if user_id == "":
            return {
                "client_id": resolved_client_id,
                "nickname": nickname,
                "profile_type": "guest",
                "stats": None,
            }

        user = account_auth_manager.store.get_user(user_id)
        if not isinstance(user, dict):
            return {
                "client_id": resolved_client_id,
                "nickname": nickname,
                "profile_type": "guest",
                "stats": None,
            }

        return {
            "client_id": resolved_client_id,
            "nickname": str(user.get("display_name") or nickname),
            "profile_type": "account",
            "stats": dict(user.get("stats") or {}),
        }

    @app.post("/api/ws-ticket")
    async def issue_ws_ticket(request: Request, payload: WsTicketIssueRequest):
        user = _resolve_current_user_or_401(request)
        client_id = str(payload.client_id or "").strip()

        if not is_valid_client_id(client_id):
            raise HTTPException(status_code=400, detail="invalid_client_id")

        try:
            user = account_auth_manager.ensure_linked_client_for_request(request, client_id)
        except HTTPException as exc:
            if exc.detail == "client_id_owned_by_other_user":
                raise HTTPException(status_code=409, detail="client_id_owned_by_other_user") from exc
            raise

        if client_id in manager.active_connections:
            raise HTTPException(status_code=409, detail="already_connected")

        ticket_payload = ws_auth_manager.issue_ticket(
            client_id=client_id,
            nickname=user.display_name,
            user_id=user.user_id,
            session_id=user.session_id,
        )
        ticket_payload["nickname"] = user.display_name
        return ticket_payload

    @app.post("/api/ws-ticket/guest")
    async def issue_guest_ws_ticket(payload: GuestWsTicketIssueRequest):
        client_id = str(payload.client_id or "").strip()
        if not is_valid_client_id(client_id):
            raise HTTPException(status_code=400, detail="invalid_client_id")

        if client_id in manager.active_connections:
            raise HTTPException(status_code=409, detail="already_connected")

        guest_nickname = sanitize_guest_nickname(payload.nickname)
        ticket_payload = ws_auth_manager.issue_guest_ticket(
            client_id=client_id,
            nickname=guest_nickname,
        )
        ticket_payload["nickname"] = guest_nickname
        return ticket_payload

    @app.get("/api/ai-models")
    async def get_ai_models():
        diag_api_log("ai_models", connected_count=len(manager.active_connections), status=200)
        return get_frontend_model_payload()

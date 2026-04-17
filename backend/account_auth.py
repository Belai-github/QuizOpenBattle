from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

try:
    from fastapi import HTTPException, Request, Response
except ImportError:  # pragma: no cover - test shell may not have app deps installed
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    Request = Any  # type: ignore
    Response = Any  # type: ignore

from backend.auth import MAX_NICKNAME_LENGTH, is_valid_client_id


SESSION_COOKIE_NAME = "quiz_session"
SESSION_MAX_AGE_SECONDS = int(os.getenv("QUIZ_SESSION_MAX_AGE_SECONDS", str(60 * 60 * 24 * 180)))
ACCOUNT_STORE_PATH = os.path.join(os.path.dirname(__file__), "storage", "data", "auth_state.json")
ACCOUNT_SCHEMA_VERSION = 1
CEREMONY_TTL_SECONDS = 300


def sanitize_account_name(raw_value: str | None) -> str:
    return str(raw_value or "").strip()[:MAX_NICKNAME_LENGTH]


def normalize_account_name_key(account_name: str) -> str:
    return str(account_name or "").strip().casefold()


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(str(value or "") + padding)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    display_name: str
    stats: dict[str, int]
    linked_client_ids: list[str]
    session_id: str
    current_client_id: str


class AccountStore:
    def __init__(self, file_path: str = ACCOUNT_STORE_PATH):
        self.file_path = file_path
        self._lock = threading.RLock()
        self._state = self._load_state()

    def _default_state(self) -> dict[str, Any]:
        return {
            "schema_version": ACCOUNT_SCHEMA_VERSION,
            "users": {},
            "credentials": {},
            "sessions": {},
            "client_links": {},
        }

    def _load_state(self) -> dict[str, Any]:
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        try:
            with open(self.file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            payload = self._default_state()
            self._persist(payload)
            return payload
        except (OSError, json.JSONDecodeError):
            payload = self._default_state()
            self._persist(payload)
            return payload

        if not isinstance(payload, dict):
            payload = self._default_state()
            self._persist(payload)
            return payload

        payload.setdefault("schema_version", ACCOUNT_SCHEMA_VERSION)
        payload.setdefault("users", {})
        payload.setdefault("credentials", {})
        payload.setdefault("sessions", {})
        payload.setdefault("client_links", {})
        return payload

    def _persist(self, payload: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        dir_path = os.path.dirname(self.file_path)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dir_path, delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, separators=(",", ":"))
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_name = tmp.name
        os.replace(temp_name, self.file_path)

    def _persist_locked(self) -> None:
        self._persist(self._state)

    def _purge_expired_sessions_locked(self, now: float | None = None) -> None:
        current = float(now or time.time())
        sessions = self._state["sessions"]
        removed = False
        for session_id, session in list(sessions.items()):
            if not isinstance(session, dict):
                sessions.pop(session_id, None)
                removed = True
                continue
            expires_at = float(session.get("expires_at") or 0)
            if expires_at > current:
                continue
            sessions.pop(session_id, None)
            removed = True

        if removed:
            self._persist_locked()

    def _default_stats(self) -> dict[str, int]:
        return {
            "matches_played": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
        }

    def _copy_stats(self, stats: Any) -> dict[str, int]:
        payload = self._default_stats()
        if isinstance(stats, dict):
            for key in payload.keys():
                payload[key] = max(0, int(stats.get(key) or 0))
        return payload

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            user = self._state["users"].get(str(user_id or ""))
            if isinstance(user, dict):
                return dict(user)
            return None

    def find_user_by_display_name(self, display_name: str) -> dict[str, Any] | None:
        target_key = normalize_account_name_key(display_name)
        if target_key == "":
            return None
        with self._lock:
            for user in self._state["users"].values():
                if not isinstance(user, dict):
                    continue
                if normalize_account_name_key(user.get("display_name")) == target_key:
                    return dict(user)
            return None

    def resolve_user_id_for_client_id(self, client_id: str) -> str | None:
        cid = str(client_id or "").strip()
        if cid == "":
            return None
        with self._lock:
            user_id = self._state["client_links"].get(cid)
            if isinstance(user_id, str) and user_id != "":
                return user_id
            return None

    def get_linked_client_ids(self, user_id: str) -> list[str]:
        with self._lock:
            user = self._state["users"].get(str(user_id or ""))
            if not isinstance(user, dict):
                return []
            linked = user.get("linked_client_ids", [])
            if not isinstance(linked, list):
                return []
            return [str(client_id) for client_id in linked if isinstance(client_id, str) and client_id != ""]

    def get_credential(self, credential_id: str) -> dict[str, Any] | None:
        with self._lock:
            credential = self._state["credentials"].get(str(credential_id or ""))
            if isinstance(credential, dict):
                return dict(credential)
            return None

    def create_user(
        self,
        display_name: str,
        user_handle_b64: str,
        credential_id: str,
        public_key_b64: str,
        sign_count: int,
        transports: list[str] | None = None,
        device_type: str | None = None,
        backed_up: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            account_name = sanitize_account_name(display_name)
            if account_name == "":
                raise ValueError("empty_display_name")
            if self.find_user_by_display_name(account_name) is not None:
                raise ValueError("display_name_taken")
            if str(credential_id or "") in self._state["credentials"]:
                raise ValueError("credential_exists")

            now_ms = int(time.time() * 1000)
            user_id = uuid.uuid4().hex
            user = {
                "user_id": user_id,
                "user_handle_b64": str(user_handle_b64 or ""),
                "display_name": account_name,
                "created_at": now_ms,
                "last_login_at": now_ms,
                "linked_client_ids": [],
                "credential_ids": [str(credential_id or "")],
                "stats": self._default_stats(),
            }
            credential = {
                "credential_id": str(credential_id or ""),
                "user_id": user_id,
                "public_key_b64": str(public_key_b64 or ""),
                "sign_count": max(0, int(sign_count or 0)),
                "transports": [str(item) for item in (transports or []) if str(item or "").strip() != ""],
                "device_type": str(device_type or ""),
                "backed_up": bool(backed_up) if backed_up is not None else None,
                "created_at": now_ms,
                "last_used_at": now_ms,
            }
            self._state["users"][user_id] = user
            self._state["credentials"][credential["credential_id"]] = credential
            self._persist_locked()
            return dict(user)

    def update_credential_sign_count(self, credential_id: str, sign_count: int) -> None:
        with self._lock:
            credential = self._state["credentials"].get(str(credential_id or ""))
            if not isinstance(credential, dict):
                return
            credential["sign_count"] = max(0, int(sign_count or 0))
            credential["last_used_at"] = int(time.time() * 1000)
            self._persist_locked()

    def touch_user_login(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            user = self._state["users"].get(str(user_id or ""))
            if not isinstance(user, dict):
                return None
            user["last_login_at"] = int(time.time() * 1000)
            self._persist_locked()
            return dict(user)

    def link_client_id(self, user_id: str, client_id: str) -> list[str]:
        cid = str(client_id or "").strip()
        if not is_valid_client_id(cid):
            raise ValueError("invalid_client_id")

        with self._lock:
            current_owner = self._state["client_links"].get(cid)
            if isinstance(current_owner, str) and current_owner not in {"", str(user_id or "")}:
                raise ValueError("client_id_owned_by_other_user")

            user = self._state["users"].get(str(user_id or ""))
            if not isinstance(user, dict):
                raise ValueError("user_not_found")

            linked = user.get("linked_client_ids", [])
            if not isinstance(linked, list):
                linked = []
                user["linked_client_ids"] = linked

            if cid not in linked:
                linked.append(cid)
                linked.sort()
            self._state["client_links"][cid] = str(user_id or "")
            self._persist_locked()
            return [str(item) for item in linked if isinstance(item, str)]

    def create_session(self, user_id: str, current_client_id: str = "") -> str:
        with self._lock:
            if str(user_id or "") not in self._state["users"]:
                raise ValueError("user_not_found")
            self._purge_expired_sessions_locked()
            session_id = secrets.token_urlsafe(32)
            now = time.time()
            self._state["sessions"][session_id] = {
                "session_id": session_id,
                "user_id": str(user_id or ""),
                "created_at": now,
                "last_seen_at": now,
                "expires_at": now + SESSION_MAX_AGE_SECONDS,
                "current_client_id": str(current_client_id or "").strip(),
            }
            self._persist_locked()
            return session_id

    def get_session(self, session_id: str, touch: bool = True) -> dict[str, Any] | None:
        sid = str(session_id or "").strip()
        if sid == "":
            return None

        with self._lock:
            self._purge_expired_sessions_locked()
            session = self._state["sessions"].get(sid)
            if not isinstance(session, dict):
                return None
            if touch:
                now = time.time()
                session["last_seen_at"] = now
                session["expires_at"] = now + SESSION_MAX_AGE_SECONDS
                self._persist_locked()
            return dict(session)

    def delete_session(self, session_id: str) -> None:
        sid = str(session_id or "").strip()
        if sid == "":
            return
        with self._lock:
            self._state["sessions"].pop(sid, None)
            self._persist_locked()

    def update_session_client_id(self, session_id: str, client_id: str) -> None:
        sid = str(session_id or "").strip()
        with self._lock:
            session = self._state["sessions"].get(sid)
            if not isinstance(session, dict):
                return
            session["current_client_id"] = str(client_id or "").strip()
            session["last_seen_at"] = time.time()
            session["expires_at"] = time.time() + SESSION_MAX_AGE_SECONDS
            self._persist_locked()

    def build_authenticated_user(self, session_id: str) -> AuthenticatedUser | None:
        session = self.get_session(session_id, touch=True)
        if session is None:
            return None
        user = self.get_user(session.get("user_id", ""))
        if user is None:
            self.delete_session(session_id)
            return None
        return AuthenticatedUser(
            user_id=str(user.get("user_id") or ""),
            display_name=str(user.get("display_name") or ""),
            stats=self._copy_stats(user.get("stats")),
            linked_client_ids=self.get_linked_client_ids(user.get("user_id", "")),
            session_id=session_id,
            current_client_id=str(session.get("current_client_id") or ""),
        )

    def record_match_result(self, team_left_user_ids: set[str], team_right_user_ids: set[str], winner: str) -> None:
        winner_text = str(winner or "")
        with self._lock:
            changed = False

            def _apply(user_id: str, result: str) -> None:
                nonlocal changed
                user = self._state["users"].get(str(user_id or ""))
                if not isinstance(user, dict):
                    return
                stats = user.get("stats")
                if not isinstance(stats, dict):
                    stats = self._default_stats()
                    user["stats"] = stats
                stats["matches_played"] = max(0, int(stats.get("matches_played") or 0)) + 1
                if result == "win":
                    stats["wins"] = max(0, int(stats.get("wins") or 0)) + 1
                elif result == "loss":
                    stats["losses"] = max(0, int(stats.get("losses") or 0)) + 1
                else:
                    stats["draws"] = max(0, int(stats.get("draws") or 0)) + 1
                changed = True

            for user_id in sorted({uid for uid in team_left_user_ids if str(uid or "").strip() != ""}):
                if winner_text == "team-left":
                    _apply(user_id, "win")
                elif winner_text == "team-right":
                    _apply(user_id, "loss")
                else:
                    _apply(user_id, "draw")

            for user_id in sorted({uid for uid in team_right_user_ids if str(uid or "").strip() != ""}):
                if winner_text == "team-right":
                    _apply(user_id, "win")
                elif winner_text == "team-left":
                    _apply(user_id, "loss")
                else:
                    _apply(user_id, "draw")

            if changed:
                self._persist_locked()


class AccountAuthManager:
    def __init__(self, store: AccountStore | None = None):
        self.store = store or AccountStore()
        self.pending_registration_ceremonies: dict[str, dict[str, Any]] = {}
        self.pending_authentication_ceremonies: dict[str, dict[str, Any]] = {}

    def _require_webauthn(self):
        try:
            import webauthn  # type: ignore
            from webauthn.helpers.structs import (  # type: ignore
                AuthenticatorSelectionCriteria,
                ResidentKeyRequirement,
                UserVerificationRequirement,
            )
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="webauthn_unavailable") from exc

        return webauthn, AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement

    def _resolve_origin(self, request: Request) -> str:
        override = str(os.getenv("QUIZ_WEBAUTHN_ORIGIN", "")).strip()
        if override != "":
            return override.rstrip("/")
        header_origin = str(request.headers.get("origin") or "").strip()
        if header_origin != "":
            return header_origin.rstrip("/")
        return str(request.base_url).rstrip("/")

    def _resolve_rp_id(self, request: Request) -> str:
        override = str(os.getenv("QUIZ_WEBAUTHN_RP_ID", "")).strip()
        if override != "":
            return override
        return str(request.url.hostname or "").strip()

    def _resolve_rp_name(self) -> str:
        return str(os.getenv("QUIZ_WEBAUTHN_RP_NAME", "")).strip() or "QuizOpenBattle"

    def _purge_pending(self) -> None:
        now = time.time()
        for mapping in (self.pending_registration_ceremonies, self.pending_authentication_ceremonies):
            for ceremony_id, payload in list(mapping.items()):
                if float(payload.get("expires_at") or 0) <= now:
                    mapping.pop(ceremony_id, None)

    def _make_public_user_payload(self, user: AuthenticatedUser) -> dict[str, Any]:
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "stats": dict(user.stats),
            "linked_client_ids": list(user.linked_client_ids),
            "current_client_id": user.current_client_id,
        }

    def _set_session_cookie(self, response: Response, session_id: str, request: Request) -> None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=(request.url.scheme == "https"),
            samesite="lax",
            path="/",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")

    def get_authenticated_user(self, request: Request) -> AuthenticatedUser | None:
        session_id = str(request.cookies.get(SESSION_COOKIE_NAME, "") or "").strip()
        if session_id == "":
            return None
        return self.store.build_authenticated_user(session_id)

    def require_authenticated_user(self, request: Request) -> AuthenticatedUser:
        user = self.get_authenticated_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="not_authenticated")
        return user

    def link_client_id_for_user(self, user_id: str, session_id: str, client_id: str) -> list[str]:
        linked = self.store.link_client_id(user_id, client_id)
        self.store.update_session_client_id(session_id, client_id)
        return linked

    def begin_registration(self, display_name: str, request: Request) -> dict[str, Any]:
        webauthn, AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement = self._require_webauthn()
        self._purge_pending()

        account_name = sanitize_account_name(display_name)
        if account_name == "":
            raise HTTPException(status_code=400, detail="empty_display_name")
        if self.store.find_user_by_display_name(account_name) is not None:
            raise HTTPException(status_code=409, detail="display_name_taken")

        rp_id = self._resolve_rp_id(request)
        if rp_id == "":
            raise HTTPException(status_code=500, detail="invalid_rp_id")

        user_handle = uuid.uuid4().bytes
        options = webauthn.generate_registration_options(
            rp_id=rp_id,
            rp_name=self._resolve_rp_name(),
            user_id=user_handle,
            user_name=account_name,
            user_display_name=account_name,
            timeout=60000,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        ceremony_id = secrets.token_urlsafe(18)
        self.pending_registration_ceremonies[ceremony_id] = {
            "display_name": account_name,
            "user_handle_b64": _base64url_encode(user_handle),
            "challenge_b64": _base64url_encode(options.challenge),
            "rp_id": rp_id,
            "expected_origin": self._resolve_origin(request),
            "expires_at": time.time() + CEREMONY_TTL_SECONDS,
        }
        return {
            "ceremony_id": ceremony_id,
            "publicKey": json.loads(webauthn.options_to_json(options)),
        }

    def finish_registration(
        self,
        ceremony_id: str,
        credential: dict[str, Any],
        request: Request,
        response: Response,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        webauthn, _, _, _ = self._require_webauthn()
        self._purge_pending()

        pending = self.pending_registration_ceremonies.pop(str(ceremony_id or ""), None)
        if not isinstance(pending, dict):
            raise HTTPException(status_code=400, detail="invalid_ceremony")
        if float(pending.get("expires_at") or 0) <= time.time():
            raise HTTPException(status_code=400, detail="expired_ceremony")

        try:
            verification = webauthn.verify_registration_response(
                credential=credential,
                expected_challenge=_base64url_decode(str(pending.get("challenge_b64") or "")),
                expected_origin=str(pending.get("expected_origin") or self._resolve_origin(request)),
                expected_rp_id=str(pending.get("rp_id") or self._resolve_rp_id(request)),
                require_user_verification=True,
            )
        except Exception as exc:  # pragma: no cover - depends on external lib
            raise HTTPException(status_code=400, detail="registration_verification_failed") from exc

        credential_id = _base64url_encode(verification.credential_id)
        public_key_b64 = _base64url_encode(verification.credential_public_key)
        try:
            user = self.store.create_user(
                display_name=str(pending.get("display_name") or ""),
                user_handle_b64=str(pending.get("user_handle_b64") or ""),
                credential_id=credential_id,
                public_key_b64=public_key_b64,
                sign_count=int(verification.sign_count or 0),
                transports=[str(item) for item in (credential.get("response", {}) or {}).get("transports", []) if str(item or "").strip() != ""],
                device_type=str(getattr(verification, "credential_device_type", "") or ""),
                backed_up=getattr(verification, "credential_backed_up", None),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        session_id = self.store.create_session(str(user.get("user_id") or ""), str(client_id or "").strip())
        self._set_session_cookie(response, session_id, request)
        if str(client_id or "").strip() != "":
            self.link_client_id_for_user(str(user.get("user_id") or ""), session_id, str(client_id or "").strip())
        authenticated = self.store.build_authenticated_user(session_id)
        if authenticated is None:
            raise HTTPException(status_code=500, detail="session_creation_failed")
        return self._make_public_user_payload(authenticated)

    def begin_authentication(self, request: Request) -> dict[str, Any]:
        webauthn, _, _, UserVerificationRequirement = self._require_webauthn()
        self._purge_pending()

        rp_id = self._resolve_rp_id(request)
        if rp_id == "":
            raise HTTPException(status_code=500, detail="invalid_rp_id")

        options = webauthn.generate_authentication_options(
            rp_id=rp_id,
            timeout=60000,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        ceremony_id = secrets.token_urlsafe(18)
        self.pending_authentication_ceremonies[ceremony_id] = {
            "challenge_b64": _base64url_encode(options.challenge),
            "rp_id": rp_id,
            "expected_origin": self._resolve_origin(request),
            "expires_at": time.time() + CEREMONY_TTL_SECONDS,
        }
        return {
            "ceremony_id": ceremony_id,
            "publicKey": json.loads(webauthn.options_to_json(options)),
        }

    def finish_authentication(
        self,
        ceremony_id: str,
        credential: dict[str, Any],
        request: Request,
        response: Response,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        webauthn, _, _, _ = self._require_webauthn()
        self._purge_pending()

        pending = self.pending_authentication_ceremonies.pop(str(ceremony_id or ""), None)
        if not isinstance(pending, dict):
            raise HTTPException(status_code=400, detail="invalid_ceremony")
        if float(pending.get("expires_at") or 0) <= time.time():
            raise HTTPException(status_code=400, detail="expired_ceremony")

        credential_id = str(credential.get("id") or credential.get("rawId") or "").strip()
        if credential_id == "":
            raise HTTPException(status_code=400, detail="missing_credential_id")
        stored_credential = self.store.get_credential(credential_id)
        if stored_credential is None:
            raise HTTPException(status_code=404, detail="credential_not_found")

        try:
            verification = webauthn.verify_authentication_response(
                credential=credential,
                expected_challenge=_base64url_decode(str(pending.get("challenge_b64") or "")),
                expected_rp_id=str(pending.get("rp_id") or self._resolve_rp_id(request)),
                expected_origin=str(pending.get("expected_origin") or self._resolve_origin(request)),
                credential_public_key=_base64url_decode(str(stored_credential.get("public_key_b64") or "")),
                credential_current_sign_count=int(stored_credential.get("sign_count") or 0),
                require_user_verification=True,
            )
        except Exception as exc:  # pragma: no cover - depends on external lib
            raise HTTPException(status_code=400, detail="authentication_verification_failed") from exc

        self.store.update_credential_sign_count(credential_id, int(verification.new_sign_count or 0))
        user_id = str(stored_credential.get("user_id") or "")
        user = self.store.touch_user_login(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user_not_found")

        session_id = self.store.create_session(user_id, str(client_id or "").strip())
        self._set_session_cookie(response, session_id, request)
        if str(client_id or "").strip() != "":
            self.link_client_id_for_user(user_id, session_id, str(client_id or "").strip())

        authenticated = self.store.build_authenticated_user(session_id)
        if authenticated is None:
            raise HTTPException(status_code=500, detail="session_creation_failed")
        return self._make_public_user_payload(authenticated)

    def logout(self, request: Request, response: Response) -> None:
        session_id = str(request.cookies.get(SESSION_COOKIE_NAME, "") or "").strip()
        if session_id != "":
            self.store.delete_session(session_id)
        self.clear_session_cookie(response)

    def can_user_access_client_id(self, user_id: str, client_id: str) -> bool:
        cid = str(client_id or "").strip()
        if cid == "":
            return False
        owner_id = self.store.resolve_user_id_for_client_id(cid)
        if owner_id is None:
            return False
        return owner_id == str(user_id or "")

    def ensure_linked_client_for_request(self, request: Request, client_id: str) -> AuthenticatedUser:
        user = self.require_authenticated_user(request)
        cid = str(client_id or "").strip()
        if not is_valid_client_id(cid):
            raise HTTPException(status_code=400, detail="invalid_client_id")
        try:
            self.link_client_id_for_user(user.user_id, user.session_id, cid)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        refreshed = self.store.build_authenticated_user(user.session_id)
        if refreshed is None:
            raise HTTPException(status_code=401, detail="not_authenticated")
        return refreshed

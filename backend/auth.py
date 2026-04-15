import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time


CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
MAX_NICKNAME_LENGTH = 24


def sanitize_nickname(raw_value: str | None) -> str:
    nickname = str(raw_value or "").strip()
    if nickname == "":
        return "ゲスト"
    return nickname[:MAX_NICKNAME_LENGTH]


def is_valid_client_id(client_id: str) -> bool:
    return bool(CLIENT_ID_PATTERN.fullmatch(str(client_id or "").strip()))


class WebSocketAuthManager:
    def __init__(self):
        secret_text = os.getenv("QUIZ_WS_AUTH_SECRET", "").strip()
        if secret_text:
            self._secret = secret_text.encode("utf-8")
        else:
            self._secret = secrets.token_bytes(32)
            print("警告: QUIZ_WS_AUTH_SECRET 未設定のため、再起動ごとに WebSocket 認証鍵が再生成されます。")

        self.ticket_ttl_seconds = 45
        self.used_ticket_nonces = {}

    def _purge_expired_nonces(self):
        now = int(time.time())
        for nonce, exp in list(self.used_ticket_nonces.items()):
            if exp <= now:
                self.used_ticket_nonces.pop(nonce, None)

    def _sign(self, payload_segment: str) -> str:
        signature = hmac.new(self._secret, payload_segment.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")

    def _decode_base64url(self, value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)

    def issue_ticket(self, client_id: str, nickname: str) -> dict:
        now = int(time.time())
        expires_at = now + self.ticket_ttl_seconds
        nonce = secrets.token_urlsafe(18)

        payload = {
            "cid": client_id,
            "nick": nickname,
            "exp": expires_at,
            "nonce": nonce,
        }
        payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        payload_segment = base64.urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")
        signature_segment = self._sign(payload_segment)

        return {
            "ticket": f"{payload_segment}.{signature_segment}",
            "expires_at": expires_at,
        }

    def verify_ticket(self, token: str, client_id: str, nickname: str) -> tuple[bool, str]:
        self._purge_expired_nonces()

        token_text = str(token or "").strip()
        if token_text.count(".") != 1:
            return False, "invalid_format"

        payload_segment, signature_segment = token_text.split(".", 1)
        expected_signature = self._sign(payload_segment)
        if not hmac.compare_digest(signature_segment, expected_signature):
            return False, "invalid_signature"

        try:
            payload_raw = self._decode_base64url(payload_segment)
            payload = json.loads(payload_raw.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return False, "invalid_payload"

        token_client_id = str(payload.get("cid", "")).strip()
        token_nickname = sanitize_nickname(payload.get("nick", ""))
        expires_at = int(payload.get("exp", 0))
        nonce = str(payload.get("nonce", "")).strip()

        if token_client_id != client_id:
            return False, "client_mismatch"
        if token_nickname != nickname:
            return False, "nickname_mismatch"
        if expires_at <= int(time.time()):
            return False, "expired"
        if nonce == "":
            return False, "invalid_nonce"
        if nonce in self.used_ticket_nonces:
            return False, "reused_ticket"

        self.used_ticket_nonces[nonce] = expires_at
        return True, "ok"

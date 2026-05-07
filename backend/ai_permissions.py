from typing import Any


def _build_access_state(
    *,
    allowed: bool,
    reason_code: str,
    message: str = "",
    title: str = "",
    cost_item_code: str | None = None,
    cost_amount: int = 0,
) -> dict[str, Any]:
    return {
        "allowed": bool(allowed),
        "reason_code": str(reason_code or "").strip() or ("ok" if allowed else "unavailable"),
        "message": str(message or "").strip(),
        "title": str(title or "").strip(),
        "cost_item_code": str(cost_item_code or "").strip() or None,
        "cost_amount": max(0, int(cost_amount or 0)),
    }


def resolve_ai_question_access(manager, client_id: str | None) -> dict[str, Any]:
    normalized_client_id = str(client_id or "").strip()
    if normalized_client_id == "":
        return _build_access_state(
            allowed=False,
            reason_code="not_connected",
            message="サーバー接続後に操作できます。",
            title="サーバー接続後に利用できます",
        )

    if manager.is_guest_client(normalized_client_id):
        return _build_access_state(
            allowed=False,
            reason_code="guest_session",
            message="AI出題機能はログイン後に利用できます。",
            title="AI出題機能はログイン後に利用できます",
        )

    if manager.ai_question_generation_active:
        is_own_generation = str(manager.ai_question_generation_owner_id or "") == normalized_client_id
        return _build_access_state(
            allowed=False,
            reason_code="generation_in_progress",
            message="AI問題を生成中です。完了するまでお待ちください。"
            if is_own_generation
            else "他のAI問題を生成中です。しばらく待ってから再試行してください。",
            title="AI問題を生成中です"
            if is_own_generation
            else "他のAI問題を生成中です",
        )

    if manager._has_active_ai_room():
        return _build_access_state(
            allowed=False,
            reason_code="active_ai_room",
            message="すでにAI出題部屋があるため、AI出題はできません。",
            title="AI出題部屋があるため使用できません",
        )

    return _build_access_state(
        allowed=True,
        reason_code="ok",
    )

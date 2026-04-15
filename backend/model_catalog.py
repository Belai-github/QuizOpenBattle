import json
import os
from typing import Any


MODELS_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "data", "models.json")

_FALLBACK_DEFAULT_MODEL_ID = "gemini-2.5-flash"
_FALLBACK_ANSWER_JUDGEMENT_MODEL_ID = "gemini-2.5-flash-lite"


def _safe_read_config() -> dict[str, Any]:
    try:
        with open(MODELS_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                return raw
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _normalize_models(raw_models: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_models, list):
        return []

    normalized: list[dict[str, Any]] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or "").strip()
        if model_id == "":
            continue
        normalized.append(
            {
                "id": model_id,
                "label": str(raw.get("label") or model_id),
                "provider": str(raw.get("provider") or "google").strip().lower(),
                "enabled": bool(raw.get("enabled", True)),
            }
        )

    if not normalized:
        return []

    return normalized


def _active_models() -> list[dict[str, Any]]:
    config = _safe_read_config()
    all_models = _normalize_models(config.get("models"))
    active = [model for model in all_models if bool(model.get("enabled", True))]
    return active


def get_available_models() -> list[dict[str, Any]]:
    return _active_models()


def get_available_model_ids() -> tuple[str, ...]:
    return tuple(model["id"] for model in _active_models())


def get_default_model_id() -> str:
    config = _safe_read_config()
    candidate = str(config.get("default_model_id") or "").strip()
    available = set(get_available_model_ids())
    if candidate in available:
        return candidate
    if _FALLBACK_DEFAULT_MODEL_ID in available:
        return _FALLBACK_DEFAULT_MODEL_ID
    return next(iter(available), _FALLBACK_DEFAULT_MODEL_ID)


def get_answer_judgement_model_id() -> str:
    config = _safe_read_config()
    candidate = str(config.get("answer_judgement_model_id") or "").strip()
    available = set(get_available_model_ids())
    if candidate in available:
        return candidate
    if _FALLBACK_ANSWER_JUDGEMENT_MODEL_ID in available:
        return _FALLBACK_ANSWER_JUDGEMENT_MODEL_ID
    return get_default_model_id()


def normalize_model_id(model_id: str | None) -> str:
    candidate = str(model_id or "").strip()
    if candidate in set(get_available_model_ids()):
        return candidate
    return get_default_model_id()


def is_openai_model(model_id: str) -> bool:
    target = str(model_id or "").strip()
    if target == "":
        return False
    for model in _active_models():
        if model.get("id") == target and model.get("provider") == "openai":
            return True
    return False


def get_frontend_model_payload() -> dict[str, Any]:
    models = _active_models()
    return {
        "default_model_id": get_default_model_id(),
        "answer_judgement_model_id": get_answer_judgement_model_id(),
        "models": [
            {
                "id": str(model.get("id") or "").strip(),
                "label": str(model.get("label") or model.get("id") or "").strip(),
                "provider": str(model.get("provider") or "google").strip(),
            }
            for model in models
        ],
    }

import json
import os
from typing import Any


_MODULE_DIR = os.path.dirname(__file__)
_MODELS_CONFIG_CANDIDATES = (
    os.path.join(_MODULE_DIR, "data", "models.json"),
    os.path.join(_MODULE_DIR, "storage", "data", "models.json"),
    # fallback: backend/data/models.json（古い構造）
    os.path.join(os.path.dirname(_MODULE_DIR), "data", "models.json"),
)
MODELS_CONFIG_PATH = next((path for path in _MODELS_CONFIG_CANDIDATES if os.path.exists(path)), _MODELS_CONFIG_CANDIDATES[0])

_FALLBACK_DEFAULT_MODEL_ID = "gemini-2.5-flash"
_FALLBACK_ANSWER_JUDGEMENT_MODEL_ID = "gemini-2.5-flash-lite"
_ALLOWED_REASONING_LEVELS = {"low", "medium", "high"}


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
        api_model = str(raw.get("model") or model_id).strip()
        label = str(raw.get("label") or model_id).strip() or model_id
        time_value = raw.get("time")
        normalized_time: int | None
        try:
            normalized_time = int(str(time_value).strip())
            if normalized_time < 0:
                normalized_time = None
        except (TypeError, ValueError):
            normalized_time = None
        reasoning = str(raw.get("reasoning") or "").strip().lower()
        normalized_reasoning = reasoning if reasoning in _ALLOWED_REASONING_LEVELS else None
        normalized.append(
            {
                "id": model_id,
                "model": api_model,
                "label": label,
                "time": normalized_time,
                "provider": str(raw.get("provider") or "google").strip().lower(),
                "reasoning": normalized_reasoning,
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


def get_model_config_by_id(model_id: str | None) -> dict[str, Any] | None:
    target = str(model_id or "").strip()
    if target == "":
        return None
    for model in _active_models():
        if model.get("id") == target:
            return model
    return None


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


def get_model_api_model(model_id: str | None) -> str:
    config = get_model_config_by_id(model_id)
    if config is None:
        return normalize_model_id(model_id)
    return str(config.get("model") or config.get("id") or "").strip() or normalize_model_id(model_id)


def get_model_provider(model_id: str | None) -> str | None:
    config = get_model_config_by_id(model_id)
    if config is None:
        return None
    provider = str(config.get("provider") or "").strip().lower()
    return provider or None


def is_openai_model(model_id: str) -> bool:
    return get_model_provider(model_id) == "openai"


def get_model_reasoning_effort(model_id: str | None) -> str | None:
    config = get_model_config_by_id(model_id)
    if config is None:
        return None
    reasoning = str(config.get("reasoning") or "").strip().lower()
    return reasoning if reasoning in _ALLOWED_REASONING_LEVELS else None


def get_model_display_label(model_id: str | None) -> str:
    config = get_model_config_by_id(model_id)
    if config is None:
        return str(model_id or "").strip()
    return str(config.get("label") or config.get("id") or "").strip()


def get_model_time_seconds(model_id: str | None) -> int | None:
    config = get_model_config_by_id(model_id)
    if config is None:
        return None
    time_value = config.get("time")
    return time_value if isinstance(time_value, int) and time_value >= 0 else None


def get_frontend_model_payload() -> dict[str, Any]:
    models = _active_models()
    return {
        "default_model_id": get_default_model_id(),
        "answer_judgement_model_id": get_answer_judgement_model_id(),
        "models": [
            {
                "id": str(model.get("id") or "").strip(),
                "model": str(model.get("model") or model.get("id") or "").strip(),
                "label": str(model.get("label") or model.get("id") or "").strip(),
                "time": model.get("time"),
                "provider": str(model.get("provider") or "google").strip(),
                "reasoning": model.get("reasoning"),
            }
            for model in models
        ],
    }

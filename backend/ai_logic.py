import os
import json
import re
import unicodedata
from difflib import SequenceMatcher
from openai import AsyncOpenAI
from google import genai
from dotenv import load_dotenv

try:
    from backend.pronpt import get_quiz_prompt, get_judge_prompt
    from backend.judge_cache import DEFAULT_PROMPT_VERSION, get_cached_answer_judgement, store_answer_judgement
    from backend.model_catalog import (
        get_answer_judgement_model_id,
        get_available_model_ids,
        get_default_model_id,
        is_openai_model,
        normalize_model_id as normalize_model_id_from_catalog,
    )
except ImportError:
    from pronpt import get_quiz_prompt, get_judge_prompt
    from judge_cache import DEFAULT_PROMPT_VERSION, get_cached_answer_judgement, store_answer_judgement
    from model_catalog import (
        get_answer_judgement_model_id,
        get_available_model_ids,
        get_default_model_id,
        is_openai_model,
        normalize_model_id as normalize_model_id_from_catalog,
    )

# .envファイルからAPIキーを環境変数として読み込む
load_dotenv()

# 新しいSDKのクライアントを初期化（環境変数 GEMINI_API_KEY が自動で使われます）
gemini_client = genai.Client()
openai_client = AsyncOpenAI()

AVAILABLE_MODEL_IDS = (*get_available_model_ids(),)
DEFAULT_MODEL_ID = get_default_model_id()
QUIZ_GENERATION_TEMPERATURE = 1.0
ANSWER_JUDGEMENT_TEMPERATURE = 0.0
DEFAULT_QUIZ_DIFFICULTY = 50
MAX_QUIZ_DIFFICULTY = 100
ANSWER_JUDGEMENT_CACHE_VERSION = DEFAULT_PROMPT_VERSION


def _is_resource_exhausted_error(error: Exception) -> bool:
    message = str(error)
    upper = message.upper()
    return "RESOURCE_EXHAUSTED" in upper or "SPENDING CAP" in upper


def _is_openai_resource_exhausted_error(error: Exception) -> bool:
    message = str(error)
    upper = message.upper()
    if "INSUFFICIENT_QUOTA" in upper or "BILLING" in upper:
        return True

    status_code = getattr(error, "status_code", None)
    if status_code in {402, 429}:
        return True

    return False


def normalize_model_id(model_id: str | None) -> str:
    return normalize_model_id_from_catalog(model_id)


def normalize_difficulty(difficulty: int | str | None) -> int:
    if difficulty is None:
        return DEFAULT_QUIZ_DIFFICULTY

    try:
        value = int(difficulty)
    except (TypeError, ValueError):
        return DEFAULT_QUIZ_DIFFICULTY

    if value < 0:
        return 0
    if 0 <= value <= 5:
        value *= 20
    if value > MAX_QUIZ_DIFFICULTY:
        return MAX_QUIZ_DIFFICULTY
    return int(round(value / 10.0) * 10)


_ANSWER_PREFIX_RE = re.compile(r"^(答え|こたえ)(は|:|：)?", re.IGNORECASE)
_ANSWER_SUFFIX_RE = re.compile(
    r"(です|でした|だと思います|だとおもいます|だと考えます|でしょう|かな|かも|ですね)[。！!？?\s]*$",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(r'[\s\u3000\-‐‑‒–—―_・,，.．。!！?？"\'\(\)\[\]【】「」『』]+')


def _katakana_to_hiragana(text: str) -> str:
    converted = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            converted.append(chr(code - 0x60))
        else:
            converted.append(ch)
    return "".join(converted)


def _normalize_answer_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    value = _ANSWER_PREFIX_RE.sub("", value)
    value = _ANSWER_SUFFIX_RE.sub("", value)
    value = _katakana_to_hiragana(value)
    value = _NOISE_RE.sub("", value)
    return value


def _fallback_answer_judgement(expected_answer: str, user_answer: str) -> bool:
    expected = _normalize_answer_text(expected_answer)
    user = _normalize_answer_text(user_answer)

    if expected == "" or user == "":
        return False

    if expected == user:
        return True

    min_len = min(len(expected), len(user))
    if min_len >= 2 and (expected in user or user in expected):
        return True

    similarity = SequenceMatcher(a=expected, b=user).ratio()
    return similarity >= 0.9


async def generate_quiz_async(genre="一般常識", model_id: str | None = None, difficulty: int | str | None = 0):
    """Gemini APIを叩いてクイズを1問生成する非同期関数"""

    normalized_difficulty = normalize_difficulty(difficulty)
    prompt = get_quiz_prompt(genre, normalized_difficulty)
    selected_model_id = normalize_model_id(model_id)

    if is_openai_model(selected_model_id):
        try:
            response = await openai_client.chat.completions.create(
                model=selected_model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "あなたはクイズ作成アシスタントです。必ずJSONオブジェクトのみを返してください。",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=QUIZ_GENERATION_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            response_text = (response.choices[0].message.content or "").strip()
            return json.loads(response_text)
        except Exception as e:
            if _is_openai_resource_exhausted_error(e):
                print(
                    "クイズ生成エラー(OpenAI 課金上限):",
                    {
                        "model_id": selected_model_id,
                        "genre": genre,
                        "difficulty": normalized_difficulty,
                        "error": repr(e),
                    },
                )
                return {
                    "question": "",
                    "answer": "",
                    "error_code": "RESOURCE_EXHAUSTED",
                    "error_message": "Your OpenAI project has exceeded its quota or billing limit.",
                }

            print(
                "クイズ生成エラー(OpenAI):",
                {
                    "model_id": selected_model_id,
                    "genre": genre,
                    "difficulty": normalized_difficulty,
                    "error": repr(e),
                },
            )
            return {"question": "AI問題の生成に失敗しました。", "answer": "エラー"}

    try:
        # 新しいSDKの非同期メソッド (client.aio) を使用して呼び出し
        response = await gemini_client.aio.models.generate_content(
            model=selected_model_id,
            contents=prompt,
            config={
                "temperature": QUIZ_GENERATION_TEMPERATURE,
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                    },
                    "required": ["question", "answer"],
                    # "additionalProperties": False,  # 未対応なので削除
                },
            },
        )

        # 可能なら parsed を優先
        if getattr(response, "parsed", None):
            quiz_data = response.parsed
        else:
            response_text = response.text or ""
            quiz_data = json.loads(response_text)

        return quiz_data

    except Exception as e:
        if _is_resource_exhausted_error(e):
            print(
                "クイズ生成エラー(Gemini 課金上限):",
                {
                    "model_id": selected_model_id,
                    "genre": genre,
                    "difficulty": normalized_difficulty,
                    "error": repr(e),
                },
            )
            return {
                "question": "",
                "answer": "",
                "error_code": "RESOURCE_EXHAUSTED",
                "error_message": "Your project has exceeded its spending cap.",
            }

        print(
            "クイズ生成エラー(Gemini):",
            {
                "model_id": selected_model_id,
                "genre": genre,
                "difficulty": normalized_difficulty,
                "error": repr(e),
            },
        )
        return {"question": "AI問題の生成に失敗しました。", "answer": "エラー"}


async def check_answer_async(expected_answer: str, user_answer: str):
    """プレイヤーの解答が正解と意味的に同じか判定する非同期関数"""

    if expected_answer == user_answer:
        return True

    selected_model_id = get_answer_judgement_model_id()
    cached_result = get_cached_answer_judgement(
        expected_answer,
        user_answer,
        selected_model_id,
        ANSWER_JUDGEMENT_CACHE_VERSION,
    )
    if cached_result is not None:
        return cached_result

    prompt = get_judge_prompt(expected_answer, user_answer)

    try:
        response = await gemini_client.aio.models.generate_content(
            model=selected_model_id,
            contents=prompt,
            config={"temperature": ANSWER_JUDGEMENT_TEMPERATURE},
        )
        response_text = response.text or ""
        result_text = response_text.strip().lower()

        is_correct = result_text == "true"
        store_answer_judgement(
            expected_answer,
            user_answer,
            selected_model_id,
            ANSWER_JUDGEMENT_CACHE_VERSION,
            is_correct,
            source="gemini",
        )
        return is_correct

    except Exception as e:
        if _is_resource_exhausted_error(e):
            print("判定エラー(Gemini 課金上限): RESOURCE_EXHAUSTED -> ローカル簡易判定にフォールバックします")
            return _fallback_answer_judgement(expected_answer, user_answer)

        print(f"判定エラー(Gemini): {e} -> ローカル簡易判定にフォールバックします")
        return _fallback_answer_judgement(expected_answer, user_answer)


# --- 単独で実行した時のテスト用コード ---
if __name__ == "__main__":
    import asyncio
    import time

    async def test_quiz_generation(model_id: str | None = None, genre: str = "一般常識", difficulty: int | str | None = 0):
        print(f"モデル: {model_id or DEFAULT_MODEL_ID}", f"ジャンル: {genre}", f"正答率目安: {normalize_difficulty(difficulty)}%")
        print("クイズを生成中...")
        t = time.time()
        quiz = await generate_quiz_async(genre, model_id, difficulty)
        dt = time.time() - t
        quiz_dict = quiz if isinstance(quiz, dict) else {}
        question = str(quiz_dict.get("question", ""))
        answer = str(quiz_dict.get("answer", ""))
        print(f"生成にかかった時間: {dt:.2f}秒")
        print(f"問題: {question}")
        print(f"答え: {answer}")
        print()

    async def alltest(genre: str = "一般常識", difficulty: int | str | None = 0):
        for model in get_available_model_ids():
            await test_quiz_generation(model_id=model, genre=genre, difficulty=difficulty)

    async def main():
        genre = "アニメ・マンガ"
        difficulty = 30
        await test_quiz_generation(model_id=get_default_model_id(), genre=genre, difficulty=difficulty)

    asyncio.run(main())

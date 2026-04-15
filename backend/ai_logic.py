import os
import json
import re
import unicodedata
from difflib import SequenceMatcher
from google import genai
from dotenv import load_dotenv

try:
    from backend.pronpt import difficulties as QUIZ_DIFFICULTIES, get_quiz_prompt, get_judge_prompt
except ImportError:
    from pronpt import difficulties as QUIZ_DIFFICULTIES, get_quiz_prompt, get_judge_prompt

# .envファイルからAPIキーを環境変数として読み込む
load_dotenv()

# 新しいSDKのクライアントを初期化（環境変数 GEMINI_API_KEY が自動で使われます）
client = genai.Client()

AVAILABLE_MODEL_IDS = (
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3.1-flash-lite-preview",
)
DEFAULT_MODEL_ID = "gemini-3.1-flash-lite-preview"
QUIZ_GENERATION_TEMPERATURE = 1.9
ANSWER_JUDGEMENT_TEMPERATURE = 0.0
DEFAULT_QUIZ_DIFFICULTY = 0
MAX_QUIZ_DIFFICULTY = max(0, len(QUIZ_DIFFICULTIES) - 1)


def _is_resource_exhausted_error(error: Exception) -> bool:
    message = str(error)
    upper = message.upper()
    return "RESOURCE_EXHAUSTED" in upper or "SPENDING CAP" in upper


def normalize_model_id(model_id: str | None) -> str:
    candidate = str(model_id or "").strip()
    if candidate in AVAILABLE_MODEL_IDS:
        return candidate
    return DEFAULT_MODEL_ID


def normalize_difficulty(difficulty: int | str | None) -> int:
    if difficulty is None:
        return DEFAULT_QUIZ_DIFFICULTY

    try:
        value = int(difficulty)
    except (TypeError, ValueError):
        return DEFAULT_QUIZ_DIFFICULTY

    if value < 0:
        return 0
    if value > MAX_QUIZ_DIFFICULTY:
        return MAX_QUIZ_DIFFICULTY
    return value


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

    try:
        # 新しいSDKの非同期メソッド (client.aio) を使用して呼び出し
        response = await client.aio.models.generate_content(
            model=selected_model_id,
            contents=prompt,
            config={"temperature": QUIZ_GENERATION_TEMPERATURE},
        )

        response_text = response.text or ""
        raw_text = response_text.strip().replace("```json", "").replace("```", "")
        quiz_data = json.loads(raw_text)

        return quiz_data

    except Exception as e:
        if _is_resource_exhausted_error(e):
            print(
                "クイズ生成エラー(課金上限):",
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
            "クイズ生成エラー:",
            {
                "model_id": selected_model_id,
                "genre": genre,
                "difficulty": normalized_difficulty,
                "error": repr(e),
            },
        )
        return {"question": "AI問題の生成に失敗しました。", "answer": "エラー"}


async def check_answer_async(expected_answer: str, user_answer: str, model_id: str | None = None):
    """プレイヤーの解答が正解と意味的に同じか判定する非同期関数"""

    if expected_answer == user_answer:
        return True

    prompt = get_judge_prompt(expected_answer, user_answer)
    _ = model_id
    selected_model_id = DEFAULT_MODEL_ID

    try:
        response = await client.aio.models.generate_content(
            model=selected_model_id,
            contents=prompt,
            config={"temperature": ANSWER_JUDGEMENT_TEMPERATURE},
        )
        response_text = response.text or ""
        result_text = response_text.strip().lower()

        return "true" in result_text

    except Exception as e:
        if _is_resource_exhausted_error(e):
            print("判定エラー(課金上限): RESOURCE_EXHAUSTED -> ローカル簡易判定にフォールバックします")
            return _fallback_answer_judgement(expected_answer, user_answer)

        print(f"判定エラー: {e} -> ローカル簡易判定にフォールバックします")
        return _fallback_answer_judgement(expected_answer, user_answer)


# --- 単独で実行した時のテスト用コード ---
if __name__ == "__main__":
    import asyncio
    import time

    async def test_quiz_generation(model_id: str | None = None, genre: str = "一般常識", difficulty: int | str | None = 0):
        print(f"モデル: {model_id or DEFAULT_MODEL_ID}", f"ジャンル: {genre}", f"難易度: {QUIZ_DIFFICULTIES[normalize_difficulty(difficulty)]}")
        print("クイズを生成中...")
        t = time.time()
        quiz = await generate_quiz_async(genre, model_id, difficulty)
        dt = time.time() - t
        print(f"生成にかかった時間: {dt:.2f}秒")
        print(f"問題: {quiz['question']}")
        print(f"答え: {quiz['answer']}")
        print()

    async def alltest():
        for model in AVAILABLE_MODEL_IDS:
            await test_quiz_generation(model_id=model)

    model_id = "gemini-3.1-flash-lite-preview"
    genre = "一般教養"
    difficulty = 4
    # asyncio.run(alltest())
    asyncio.run(test_quiz_generation(model_id=model_id, genre=genre, difficulty=difficulty))

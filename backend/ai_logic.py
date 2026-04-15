import os
import json
from google import genai
from dotenv import load_dotenv
from pronpt import get_quiz_prompt, get_judge_prompt

# .envファイルからAPIキーを環境変数として読み込む
load_dotenv()

# 新しいSDKのクライアントを初期化（環境変数 GEMINI_API_KEY が自動で使われます）
client = genai.Client()

# 現在の最新安定・高速モデルを指定
MODEL_ID = "gemini-2.5-flash"


async def generate_quiz_async(genre="一般常識"):
    """Gemini APIを叩いてクイズを1問生成する非同期関数"""

    prompt = get_quiz_prompt(genre)

    try:
        # 新しいSDKの非同期メソッド (client.aio) を使用して呼び出し
        response = await client.aio.models.generate_content(model=MODEL_ID, contents=prompt)

        response_text = response.text or ""
        raw_text = response_text.strip().replace("```json", "").replace("```", "")
        quiz_data = json.loads(raw_text)

        return quiz_data

    except Exception as e:
        print(f"クイズ生成エラー: {e}")
        return {"question": "AI問題の生成に失敗しました。", "answer": "エラー"}


async def check_answer_async(expected_answer: str, user_answer: str):
    """プレイヤーの解答が正解と意味的に同じか判定する非同期関数"""

    prompt = get_judge_prompt(expected_answer, user_answer)

    try:
        response = await client.aio.models.generate_content(model=MODEL_ID, contents=prompt)
        response_text = response.text or ""
        result_text = response_text.strip().lower()

        return "true" in result_text

    except Exception as e:
        print(f"判定エラー: {e}")
        return False


# --- 単独で実行した時のテスト用コード ---
if __name__ == "__main__":
    import asyncio

    async def test():
        print("クイズを生成中...")
        quiz = await generate_quiz_async("歴史")
        print(quiz)

        print("\n判定テスト...")
        is_correct = await check_answer_async(quiz["answer"], quiz["answer"] + "です")
        print(f"想定:{quiz['answer']} / 解答:{quiz['answer']}です -> 判定: {is_correct}")

    asyncio.run(test())

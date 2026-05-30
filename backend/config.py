from __future__ import annotations

from pathlib import Path


# フロントエンドを公開する URL パス。現在の公開先は /game。
GAME_FRONTEND_MOUNT_PATH = "/game"

# QuizGameManager が同時に受け付ける WebSocket 接続の上限。
MAX_CONNECTIONS = 10

# 切断後に「同じプレイヤーとして再接続できる権利」を保持する秒数。
RECONNECT_RESERVATION_SECONDS = 120

# storage.reconnect が切断確定を遅延させ、部屋から自動退室させるまでの猶予秒数。
DISCONNECT_GRACE_SECONDS = 30

# アリーナ/ロビーのチャット 1 件あたりの最大文字数。
CHAT_MAX_LENGTH = 200

# submit_answer / answer_attempt で受け付ける解答文字数の上限。
ANSWER_MAX_LENGTH = 100

# 連投対策として、同一クライアントのチャット投稿間に必要な最小秒数。
CHAT_MIN_INTERVAL_SECONDS = 0.8

# チャット連投制限の判定に使う時間窓の長さ。
CHAT_RATE_WINDOW_SECONDS = 10.0

# 上の時間窓内で許可する最大投稿数。
CHAT_RATE_WINDOW_MAX_MESSAGES = 5

# 問題文作成時に許可する最大文字数。
QUESTION_TEXT_MAX_LENGTH = 100

# アリーナのチーム名として保存できる最大文字数。
TEAM_NAME_MAX_LENGTH = 10

# ニックネーム/アカウント名の最大文字数。
MAX_NICKNAME_LENGTH = 24

# ゲスト入場時に自動で付ける接頭辞。
GUEST_NICKNAME_PREFIX = "ゲスト-"

# 問題文の未公開文字をマスク表示するときに使う記号。
QUESTION_MASK_CHAR = "■"

# client_id の最小文字数。auth.py のバリデーション正規表現生成に使う。
CLIENT_ID_MIN_LENGTH = 8

# client_id の最大文字数。auth.py のバリデーション正規表現生成に使う。
CLIENT_ID_MAX_LENGTH = 80

# room 内の左右チーム参加者 set へアクセスするときのキー対応表。
TEAM_SET_FIELD_BY_KEY = {
    "team-left": "left_participants",
    "team-right": "right_participants",
}

# room 内の左右チーム表示順 list へアクセスするときのキー対応表。
TEAM_ORDER_FIELD_BY_KEY = {
    "team-left": "left_participant_order",
    "team-right": "right_participant_order",
}

# room 内の左右チーム名フィールドへアクセスするときのキー対応表。
TEAM_NAME_FIELD_BY_KEY = {
    "team-left": "left_team_name",
    "team-right": "right_team_name",
}

# チーム名未設定時にゲーム画面へ表示するデフォルト名。
DEFAULT_TEAM_NAME_BY_KEY = {
    "team-left": "先攻",
    "team-right": "後攻",
}

# 認証済みセッションをブラウザ cookie に保存するときのキー名。
SESSION_COOKIE_NAME = "quiz_session"

# セッション cookie/サーバー側セッションを既定で保持する秒数。
DEFAULT_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 180

# WebAuthn アカウント情報を保存する JSON ファイルの場所。
ACCOUNT_STORE_PATH = str(Path(__file__).resolve().parent / "storage" / "data" / "auth_state.json")

# auth_state.json のスキーマバージョン。
ACCOUNT_SCHEMA_VERSION = 1

# WebAuthn 登録/認証 ceremony を有効とみなす秒数。
CEREMONY_TTL_SECONDS = 300

# WebSocket 接続用署名チケットの有効秒数。
WEBSOCKET_TICKET_TTL_SECONDS = 45

# アカウント引き継ぎコードを有効とみなす秒数。
ACCOUNT_TRANSFER_TTL_SECONDS = 60 * 5

# アカウント引き継ぎコードの桁数。
ACCOUNT_TRANSFER_CODE_LENGTH = 8

# アカウント引き継ぎコードの入力失敗を許容する最大回数。
ACCOUNT_TRANSFER_MAX_ATTEMPTS = 5

# AI 問題生成時にモデルへ渡す temperature。
QUIZ_GENERATION_TEMPERATURE = 1.2

# AI 正誤判定時にモデルへ渡す temperature。
ANSWER_JUDGEMENT_TEMPERATURE = 0.0

# AI 出題難易度の既定値。未入力や不正入力時のフォールバックに使う。
DEFAULT_QUIZ_DIFFICULTY = 70

# AI 出題難易度として許可する最大値。
MAX_QUIZ_DIFFICULTY = 100

# generate_quiz_async の待機タイムアウト秒数。
AI_QUIZ_GENERATION_TIMEOUT_SECONDS = 100.0

# check_answer_async の待機タイムアウト秒数。
AI_ANSWER_JUDGEMENT_TIMEOUT_SECONDS = 12.0

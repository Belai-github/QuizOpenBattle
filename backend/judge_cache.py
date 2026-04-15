import hashlib
import os
import re
import sqlite3
import threading
import time
import unicodedata


DEFAULT_CACHE_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "judge_cache.db")
DEFAULT_PROMPT_VERSION = 1

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


class AnswerJudgmentCache:
    def __init__(self, db_path: str = DEFAULT_CACHE_DB_PATH):
        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._disabled = False
        self._disabled_reason = ""

    def _ensure_dir(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        self._ensure_dir()
        connection = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS answer_judgments (
                cache_key TEXT PRIMARY KEY,
                expected_normalized TEXT NOT NULL,
                user_normalized TEXT NOT NULL,
                model_id TEXT NOT NULL,
                prompt_version INTEGER NOT NULL,
                is_correct INTEGER NOT NULL,
                source TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_answer_judgments_lookup
            ON answer_judgments(expected_normalized, user_normalized, model_id, prompt_version)
            """
        )
        return connection

    def _get_connection(self) -> sqlite3.Connection | None:
        if self._disabled:
            return None

        if self._connection is not None:
            return self._connection

        with self._lock:
            if self._connection is not None:
                return self._connection

            try:
                self._connection = self._connect()
            except Exception as error:
                self._disabled = True
                self._disabled_reason = repr(error)
                self._connection = None
                return None

        return self._connection

    @staticmethod
    def make_cache_key(expected_answer: str, user_answer: str, model_id: str, prompt_version: int) -> str:
        expected_normalized = _normalize_answer_text(expected_answer)
        user_normalized = _normalize_answer_text(user_answer)
        material = "\u241f".join(
            [
                str(prompt_version),
                str(model_id or ""),
                expected_normalized,
                user_normalized,
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def get(self, expected_answer: str, user_answer: str, model_id: str, prompt_version: int) -> bool | None:
        connection = self._get_connection()
        if connection is None:
            return None

        expected_normalized = _normalize_answer_text(expected_answer)
        user_normalized = _normalize_answer_text(user_answer)
        cache_key = self.make_cache_key(expected_answer, user_answer, model_id, prompt_version)

        with self._lock:
            try:
                row = connection.execute(
                    """
                    SELECT is_correct
                    FROM answer_judgments
                    WHERE cache_key = ?
                    """,
                    (cache_key,),
                ).fetchone()
                if row is None:
                    return None

                connection.execute(
                    """
                    UPDATE answer_judgments
                    SET hit_count = hit_count + 1,
                        updated_at = ?
                    WHERE cache_key = ?
                    """,
                    (int(time.time() * 1000), cache_key),
                )
                return bool(int(row["is_correct"]))
            except Exception:
                return None

    def set(
        self,
        expected_answer: str,
        user_answer: str,
        model_id: str,
        prompt_version: int,
        is_correct: bool,
        source: str = "gemini",
    ) -> None:
        connection = self._get_connection()
        if connection is None:
            return

        expected_normalized = _normalize_answer_text(expected_answer)
        user_normalized = _normalize_answer_text(user_answer)
        cache_key = self.make_cache_key(expected_answer, user_answer, model_id, prompt_version)
        now_ms = int(time.time() * 1000)

        with self._lock:
            try:
                connection.execute(
                    """
                    INSERT INTO answer_judgments (
                        cache_key,
                        expected_normalized,
                        user_normalized,
                        model_id,
                        prompt_version,
                        is_correct,
                        source,
                        created_at,
                        updated_at,
                        hit_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        expected_normalized = excluded.expected_normalized,
                        user_normalized = excluded.user_normalized,
                        model_id = excluded.model_id,
                        prompt_version = excluded.prompt_version,
                        is_correct = excluded.is_correct,
                        source = excluded.source,
                        updated_at = excluded.updated_at
                    """,
                    (
                        cache_key,
                        expected_normalized,
                        user_normalized,
                        str(model_id or ""),
                        int(prompt_version),
                        1 if is_correct else 0,
                        str(source or "gemini"),
                        now_ms,
                        now_ms,
                    ),
                )
            except Exception:
                return


_CACHE = AnswerJudgmentCache()


def get_cached_answer_judgement(expected_answer: str, user_answer: str, model_id: str, prompt_version: int) -> bool | None:
    return _CACHE.get(expected_answer, user_answer, model_id, prompt_version)


def store_answer_judgement(
    expected_answer: str,
    user_answer: str,
    model_id: str,
    prompt_version: int,
    is_correct: bool,
    source: str = "gemini",
) -> None:
    _CACHE.set(expected_answer, user_answer, model_id, prompt_version, is_correct, source=source)

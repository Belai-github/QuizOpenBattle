from typing import Any, Callable, Literal, TypeVar, cast

from pydantic import BaseModel


MessageModelT = TypeVar("MessageModelT", bound="BaseMessage")


class BaseMessage(BaseModel):
    type: str

    @property
    def action(self) -> str:
        return str(self.type or "").strip()


class RoomExitMessage(BaseMessage):
    type: Literal["room_exit"]


class QuestionSubmissionMessage(BaseMessage):
    type: Literal["question_submission"]
    question_text: str | None = None
    content: str | None = None
    is_ai_mode: bool = False
    model_id: str | None = None
    genre: str | None = None
    difficulty: int | str | None = None
    accuracy_rate: int | str | None = None
    selected_char_indexes: list[int] | None = None
    questioner_name: str | None = None
    questioner_id: str | None = None


class LegacyQuestionSubmissionMessage(QuestionSubmissionMessage):
    type: Literal["question_submission"] = "question_submission"


class ChatMessage(BaseMessage):
    type: Literal["chat_message"]
    message: str = ""
    chat_type: str = "lobby"


class StartGameMessage(BaseMessage):
    type: Literal["start_game"]
    selected_char_indexes: list[int] | None = None


class ShuffleParticipantsMessage(BaseMessage):
    type: Literal["shuffle_participants"]


class SwapParticipantTeamMessage(BaseMessage):
    type: Literal["swap_participant_team"]
    target_client_id: str = ""


class OpenCharacterMessage(BaseMessage):
    type: Literal["open_character"]
    char_index: int | None = None


class OpenVoteRequestMessage(BaseMessage):
    type: Literal["open_vote_request"]
    char_index: int | None = None


class OpenVoteResponseMessage(BaseMessage):
    type: Literal["open_vote_response"]
    vote_id: str = ""
    approve: bool = False


class AnswerVoteResponseMessage(BaseMessage):
    type: Literal["answer_vote_response"]
    vote_id: str = ""
    approve: bool = False


class TurnEndVoteResponseMessage(BaseMessage):
    type: Literal["turn_end_vote_response"]
    vote_id: str = ""
    approve: bool = False


class IntentionalDrawVoteRequestMessage(BaseMessage):
    type: Literal["intentional_draw_vote_request"]


class IntentionalDrawVoteResponseMessage(BaseMessage):
    type: Literal["intentional_draw_vote_response"]
    vote_id: str = ""
    approve: bool = False


class SubmitAnswerMessage(BaseMessage):
    type: Literal["submit_answer"]
    is_correct: bool = False


class AnswerAttemptMessage(BaseMessage):
    type: Literal["answer_attempt"]
    answer_text: str = ""


class JudgeAnswerMessage(BaseMessage):
    type: Literal["judge_answer"]
    is_correct: bool = False


class FullOpenSettlementJudgeMessage(BaseMessage):
    type: Literal["full_open_settlement_judge"]
    vote_id: str = ""
    left_is_correct: bool = False
    right_is_correct: bool = False


class TurnEndAttemptMessage(BaseMessage):
    type: Literal["turn_end_attempt", "end_turn"]


class RoomEntryMessage(BaseMessage):
    type: Literal["room_entry"]
    room_owner_id: str = ""
    role: Literal["participant", "spectator"]


class CancelQuestionMessage(BaseMessage):
    type: Literal["cancel_question"]
    room_owner_id: str = ""


def validate_message(model_cls: type[MessageModelT], payload: Any) -> MessageModelT:
    validator = cast(Callable[[Any], object] | None, getattr(model_cls, "model_validate", None))
    if callable(validator):
        return cast(MessageModelT, validator(payload))
    return cast(MessageModelT, model_cls.parse_obj(payload))


def dump_message(message: BaseMessage) -> dict[str, Any]:
    dumper = cast(Callable[..., object] | None, getattr(message, "model_dump", None))
    if callable(dumper):
        return cast(dict[str, Any], dumper(exclude_none=True))
    return cast(dict[str, Any], message.dict(exclude_none=True))

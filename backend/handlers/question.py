from backend.schemas import QuestionSubmissionMessage


async def process_question(manager, player_id: str, payload: QuestionSubmissionMessage):
    return await manager._process_question_impl(player_id, payload)

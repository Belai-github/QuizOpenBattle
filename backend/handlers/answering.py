from backend.schemas import AnswerAttemptMessage, FullOpenSettlementJudgeMessage, JudgeAnswerMessage


async def submit_answer_attempt(manager, client_id: str, payload: AnswerAttemptMessage):
    return await manager._submit_answer_attempt_impl(client_id, payload.answer_text)


async def judge_answer(manager, client_id: str, payload: JudgeAnswerMessage):
    return await manager._judge_answer_impl(client_id, payload.is_correct)


async def judge_full_open_settlement(manager, client_id: str, payload: FullOpenSettlementJudgeMessage):
    return await manager._judge_full_open_settlement_impl(
        client_id,
        payload.vote_id,
        payload.left_is_correct,
        payload.right_is_correct,
    )

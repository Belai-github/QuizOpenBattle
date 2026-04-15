async def submit_answer_attempt(manager, client_id: str, answer_text: str):
    return await manager._submit_answer_attempt_impl(client_id, answer_text)


async def judge_answer(manager, client_id: str, is_correct: bool):
    return await manager._judge_answer_impl(client_id, is_correct)


async def judge_full_open_settlement(manager, client_id: str, vote_id: str, left_is_correct: bool, right_is_correct: bool):
    return await manager._judge_full_open_settlement_impl(client_id, vote_id, left_is_correct, right_is_correct)

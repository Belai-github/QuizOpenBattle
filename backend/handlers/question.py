async def process_question(manager, player_id: str, payload: dict):
    return await manager._process_question_impl(player_id, payload)

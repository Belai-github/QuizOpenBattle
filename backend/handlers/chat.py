async def process_chat_message(manager, client_id: str, payload: dict):
    return await manager._process_chat_message_impl(client_id, payload)

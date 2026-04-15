from backend.schemas import ChatMessage


async def process_chat_message(manager, client_id: str, payload: ChatMessage):
    return await manager._process_chat_message_impl(client_id, payload)

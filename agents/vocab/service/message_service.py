from asyncio.log import logger
from datetime import datetime
from livekit.agents.llm.chat_context import ChatContext, FunctionCall, FunctionCallOutput, ChatMessage as LivekitChatMessage, ChatItem
from bamboo_shared.repositories import ChatRepository
from bamboo_shared.enums.vocabulary import VocabularyPhase
from bamboo_shared.service.vocabulary import VocabPlanService

class MessageService:
    def __init__(self, user_id: int, chat_id: str):
        self.user_id = user_id
        self.chat_id = chat_id
        self.chat_repo = ChatRepository(user_id)

    async def get_chat_context_and_phase(self) -> tuple[ChatContext, VocabularyPhase, datetime | None]:
        vocab_service = VocabPlanService()
        chat_id_list = await vocab_service.get_current_group_chat_ids(self.user_id)
        conversation_thread_msgs = await self.chat_repo.get_chat_messages_by_chat_ids(chat_id_list)
        chat_context_items: list[ChatItem] = []

        for msg in conversation_thread_msgs:
            if msg.meta_data.get("is_transition"):
                continue

            if msg.type == "function_call":
                logger.info(f"msg.content: {msg.content}")
                chat_context_items.append(FunctionCall(
                    id=msg.id,
                    type="function_call",
                    call_id=msg.content["call_id"],
                    name=msg.content["function"]["name"],
                    arguments=msg.content["function"]["arguments"],
                ))
            elif msg.type == "function_call_output":
                chat_context_items.append(FunctionCallOutput(
                    id=msg.id,
                    type="function_call_output",
                    call_id=msg.content["tool_call_id"],
                    name=msg.content["tool_name"],
                    output=msg.content["output"],
                    is_error=True if msg.content["error"] else False,
                ))
            else:
                logger.info(f"msg.type: {msg.type}")
                chat_context_items.append(LivekitChatMessage(
                    id=msg.id,
                    type="message",
                    role=msg.author.get("role"),
                    content=[msg.content],
                    created_at=msg.create_time.timestamp(),
                ))

        phase = conversation_thread_msgs[-1].meta_data.get("phase") if conversation_thread_msgs else VocabularyPhase.WORD_CREATION_LOGIC.value
        last_communication_time = conversation_thread_msgs[-1].create_time if conversation_thread_msgs else None
        return ChatContext(items=chat_context_items), VocabularyPhase(phase), last_communication_time
        
from datetime import datetime
from asyncio.log import logger
from livekit.agents.llm.chat_context import ChatContext, FunctionCall, FunctionCallOutput, ChatMessage as LivekitChatMessage, ChatItem
from bamboo_shared.repositories import ChatRepository
from bamboo_shared.models import ChatMessage
from typing import List, Set
from sqlalchemy import func, Boolean, select
from bamboo_shared.database import async_session_maker
from bamboo_shared.enums.vocabulary import VocabularyPhase


class MessageService:
    def __init__(self, user_id: int, chat_id: str):
        self.user_id = user_id
        self.chat_id = chat_id
        self.chat_repo = ChatRepository(user_id)

    async def get_cross_chat_history(
        self, 
        chat_id: str, 
        max_depth: int = 2, 
        max_messages: int = 20
    ) -> list[ChatMessage]:
        
        """
        get the history messages of cross-chat, including the related context of previous word learning
        
        Args:
            chat_id: the current chat ID
            max_depth: the maximum depth of cross-chat
            max_messages: the maximum number of messages
            
        Returns:
            the list of messages of cross-chat
        """
        try:
            all_messages: List[ChatMessage] = []
            visited_chats: Set[str] = set()
            current_chat_id = chat_id
            depth = 0
            
            while current_chat_id and depth < max_depth and len(all_messages) < max_messages:
                # Avoid circular references
                if current_chat_id in visited_chats:
                    break
                    
                visited_chats.add(current_chat_id)
                
                transition_message = None
                last_message_id = None
                
                # First. Try to find the transition message
                async with async_session_maker() as session:
                    transition_message = await session.execute(
                        select(ChatMessage)
                        .where(
                            ChatMessage.chat_id == current_chat_id,
                            ChatMessage.user_id == self.user_id,
                            func.JSON_EXTRACT(ChatMessage.meta_data, '$.is_transition').cast(Boolean).is_(True)
                        )
                        .order_by(ChatMessage.create_time.asc())
                        .limit(1)
                    )
                    transition_message = transition_message.scalar_one_or_none()
                
                if not transition_message:
                    return []
                
                last_message_id = transition_message.meta_data.get("parent_message_id")
                parent_chat_id = transition_message.meta_data.get("parent_chat_id")
                # get the complete conversation thread
                if last_message_id:
                    thread_messages = await self.chat_repo.get_conversation_thread_msgs(
                        parent_chat_id,
                        last_message_id
                    )
                    all_messages.extend(thread_messages)
                    
                    # If there is a transition message, get the previous chat information from the metadata
                    current_chat_id = transition_message.meta_data.get("parent_chat_id")
                    depth += 1
                else:
                    break
                    
            # Ensure we don't exceed max_messages by returning only the most recent messages
            if len(all_messages) > max_messages:
                all_messages = all_messages[-max_messages:]
            return all_messages
        except Exception as e:
            logger.error(f"Error getting cross-chat history: {str(e)}")
            return []
        
    async def get_chat_context_and_phase(self) -> tuple[ChatContext, VocabularyPhase, datetime | None]:
        conversation_thread_msgs = await self.get_cross_chat_history(self.chat_id)
        chat_context_items: list[ChatItem] = []

        for msg in conversation_thread_msgs:
            if msg.meta_data.get("is_transition"):
                continue

            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    chat_context_items.append(FunctionCall(
                        id=tool_call.id,
                        type="function_call",
                        call_id=tool_call.call_id,
                        name=tool_call.function.name,
                        arguments=tool_call.function.arguments,
                    ))

            if msg.tool_call_id:
                chat_context_items.append(FunctionCallOutput(
                    id=msg.id,
                    type="function_call_output",
                    call_id=msg.tool_call_id,
                    name=msg.metadata.to_dict().get("tool_name"),
                    output=msg.content,
                    is_error=msg.metadata.to_dict().get("tool_result").get("success") is False,
                ))
            else:
                chat_context_items.append(LivekitChatMessage(
                    id=msg.id,
                    type="message",
                    role=msg.author.to_dict().get("role"),
                    content=[msg.content],
                    created_at=msg.created_at,
                    interrupted=msg.interrupted,
                    hash=msg.hash,
                ))

        phase = conversation_thread_msgs[-1].meta_data.get("phase") if conversation_thread_msgs else VocabularyPhase.WORD_CREATION_LOGIC.value
        last_communication_time = conversation_thread_msgs[-1].created_at if conversation_thread_msgs else None
        return ChatContext(items=chat_context_items), VocabularyPhase(phase), last_communication_time
        
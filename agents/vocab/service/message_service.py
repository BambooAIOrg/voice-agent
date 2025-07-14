from asyncio.log import logger
from datetime import datetime
from typing import Sequence
from livekit.agents.llm.chat_context import ChatContext, FunctionCall, FunctionCallOutput, ChatMessage as LivekitChatMessage, ChatItem
from bamboo_shared.repositories import ChatRepository
from bamboo_shared.models.Chat import ChatMessage
from bamboo_shared.enums.vocabulary import VocabularyPhase
from bamboo_shared.service.vocabulary import VocabPlanService
import uuid

class MessageService:
    def __init__(self, user_id: int, chat_id: str):
        self.user_id = user_id
        self.chat_id = chat_id
        self.chat_repo = ChatRepository(user_id)
        self.current_parent_message_id: str | None = None

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
            elif msg.type == "message" and msg.content is not None:
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
        
        # Set current parent message ID to the last message for message threading
        if conversation_thread_msgs:
            self.current_parent_message_id = conversation_thread_msgs[-1].id
        
        logger.info(f"conversation_thread_msgs: {conversation_thread_msgs}")
        logger.info(f"current_parent_message_id: {self.current_parent_message_id}")
        logger.info(f"last_communication_time: {last_communication_time}")
        logger.info(f"chat_context_items: {chat_context_items}")
        return ChatContext(items=chat_context_items), VocabularyPhase(phase), last_communication_time

    async def save_user_message(self, content: str, visitor_id: str | None = None) -> str:
        """Save a user message to the database and return the message ID."""
        message_id = str(uuid.uuid4())
        
        message = ChatMessage(
            id=message_id,
            user_id=self.user_id,
            visitor_id=visitor_id,
            parent_message_id=self.current_parent_message_id,
            chat_id=self.chat_id,
            model="",
            type="message",
            status="finished_successfully",
            author={"role": "user"},
            content=content,
            end_turn=True,
            meta_data={}
        )
        
        await self.chat_repo.save_messages([message])
        self.current_parent_message_id = message_id
        return message_id

    async def save_assistant_message(self, content: str, phase: VocabularyPhase | None = None, meta_data: dict | None = None) -> str:
        """Save an assistant message to the database and return the message ID."""
        message_id = str(uuid.uuid4())
        
        message_meta_data = meta_data or {}
        if phase:
            message_meta_data["phase"] = phase.value
        
        message = ChatMessage(
            id=message_id,
            user_id=self.user_id,
            visitor_id=None,
            parent_message_id=self.current_parent_message_id,
            chat_id=self.chat_id,
            model="openai",
            type="message",
            status="finished_successfully",
            author={"role": "assistant"},
            content=content,
            end_turn=True,
            meta_data=message_meta_data
        )
        
        await self.chat_repo.save_messages([message])
        self.current_parent_message_id = message_id
        return message_id

    async def save_function_call_message(self, function_call: FunctionCall) -> str:
        """Save a function call message to the database and return the message ID."""
        message_id = str(uuid.uuid4())
        
        message = ChatMessage(
            id=message_id,
            user_id=self.user_id,
            visitor_id=None,
            parent_message_id=self.current_parent_message_id,
            chat_id=self.chat_id,
            model="openai",
            type="function_call",
            status="finished_successfully",
            author={"role": "assistant"},
            content={
                "call_id": function_call.call_id,
                "function": {
                    "name": function_call.name,
                    "arguments": function_call.arguments
                }
            },
            end_turn=False,
            meta_data={}
        )
        
        await self.chat_repo.save_messages([message])
        self.current_parent_message_id = message_id
        return message_id

    async def save_function_output_message(self, function_output: FunctionCallOutput) -> str:
        """Save a function call output message to the database and return the message ID."""
        message_id = str(uuid.uuid4())
        
        message = ChatMessage(
            id=message_id,
            user_id=self.user_id,
            visitor_id=None,
            parent_message_id=self.current_parent_message_id,
            chat_id=self.chat_id,
            model="",
            type="function_call_output",
            status="finished_successfully",
            author={"role": "tool"},
            content={
                "tool_call_id": function_output.call_id,
                "call_id": function_output.call_id,
                "output": function_output.output,
                "tool_name": function_output.name,
                "success": not function_output.is_error,
                "error": None if not function_output.is_error else "Function execution failed"
            },
            end_turn=False,
            meta_data={}
        )
        
        await self.chat_repo.save_messages([message])
        self.current_parent_message_id = message_id
        return message_id

    async def save_messages_batch(self, messages: Sequence[ChatMessage]) -> None:
        """Save multiple messages to the database in a batch."""
        await self.chat_repo.save_messages(messages)
        if messages:
            self.current_parent_message_id = messages[-1].id
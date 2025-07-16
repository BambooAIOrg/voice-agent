from livekit.agents.llm.chat_context import FunctionCall, FunctionCallOutput
from bamboo_shared.repositories import ChatRepository
from bamboo_shared.models.Chat import ChatMessage
import uuid
from agents.vocab.context import AgentContext
from bamboo_shared.logger import get_logger

logger = get_logger(__name__)

class MessageService:
    def __init__(self, user_id: int, context: AgentContext):
        self.user_id = user_id
        self.context = context
        self.chat_repo = ChatRepository(user_id)

    async def save_user_message(self, content: str, meta_data: dict | None = None) -> str:
        """Save a user message to the database and return the message ID."""
        message_id = str(uuid.uuid4())
        
        chat_id = self.context.chat_id
        if not chat_id:
            raise ValueError("chat_id is None")
        
        message = ChatMessage(
            id=message_id,
            user_id=self.user_id,
            visitor_id=None,
            parent_message_id=self.context.current_node,
            chat_id=chat_id,
            model="gpt-4.1",
            type="message",
            status="finished_successfully",
            author={"role": "user"},
            content=content,
            end_turn=True,
            meta_data=meta_data
        )
        
        await self.chat_repo.save_messages([message])
        await self.chat_repo.update_chat_current_node(message_id, chat_id)
        self.context.update_chat_current_node(message_id)
        return message_id

    async def save_assistant_message(self, content: str, meta_data: dict | None = None) -> str:
        """Save an assistant message to the database and return the message ID."""
        message_id = str(uuid.uuid4())
        chat_id = self.context.chat_id
        if not chat_id:
            raise ValueError("chat_id is None")
        
        
        message = ChatMessage(
            id=message_id,
            user_id=self.user_id,
            visitor_id=None,
            parent_message_id=self.context.current_node,
            chat_id=chat_id,
            model="gpt-4.1",
            type="message",
            status="finished_successfully",
            author={"role": "assistant"},
            content=content,
            end_turn=True,
            meta_data=meta_data
        )
        
        await self.chat_repo.save_messages([message])
        await self.chat_repo.update_chat_current_node(message_id, chat_id)
        self.context.update_chat_current_node(message_id)
        return message_id

    async def save_function_call_message(self, function_call: FunctionCall, meta_data: dict | None = None) -> str:
        """Save a function call message to the database and return the message ID."""
        message_id = str(uuid.uuid4())
        chat_id = self.context.chat_id
        if not chat_id:
            raise ValueError("chat_id is None")
        
        message = ChatMessage(
            id=message_id,
            user_id=self.user_id,
            visitor_id=None,
            parent_message_id=self.context.current_node,
            chat_id=chat_id,
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
            end_turn=True,
            meta_data=meta_data
        )
        
        await self.chat_repo.save_messages([message])
        await self.chat_repo.update_chat_current_node(message_id, chat_id)
        self.context.update_chat_current_node(message_id)
        return message_id

    async def save_function_output_message(self, function_output: FunctionCallOutput) -> str:
        """Save a function call output message to the database and return the message ID."""
        message_id = str(uuid.uuid4())
        chat_id = self.context.chat_id
        if not chat_id:
            raise ValueError("chat_id is None")
        
        message = ChatMessage(
            id=message_id,
            user_id=self.user_id,
            visitor_id=None,
            parent_message_id=self.context.current_node,
            chat_id=chat_id,
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
        await self.chat_repo.update_chat_current_node(message_id, chat_id)
        self.context.update_chat_current_node(message_id)
        return message_id
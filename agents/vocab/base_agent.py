from typing import Any, Optional

from bamboo_shared.logger import get_logger
from livekit.agents import (
    Agent,
    ConversationItemAddedEvent,
    FunctionToolsExecutedEvent,
    RunContext,
)
from livekit.agents.llm import (
    ChatContext,
    ChatMessage as LivekitChatMessage,
    FunctionCall,
    FunctionCallOutput,
)

from agents.vocab.context import AgentContext
from agents.vocab.service.message_service import MessageService

logger = get_logger(__name__)

class BaseVocabAgent(Agent):
    """Base agent class that automatically handles message persistence for vocabulary learning agents."""
    
    def __init__(self, context: AgentContext, **kwargs):
        super().__init__(**kwargs)
        self.context = context
        self.message_service = MessageService(context.user_info.id, context.chat_id)
    
    async def on_enter(self):
        """Setup event handlers for message persistence when agent enters."""
        logger.info("BaseVocabAgent on_enter")
        # Set up event listeners for message persistence
        @self.session.on("conversation_item_added")
        async def on_conversation_item_added(event: ConversationItemAddedEvent):
            """Save messages when they are added to the conversation."""
            await self._handle_conversation_item_added(event)
        
        @self.session.on("function_tools_executed")
        async def on_function_tools_executed(event: FunctionToolsExecutedEvent):
            """Save function calls and outputs when tools are executed."""
            await self._handle_function_tools_executed(event)
        
        # Call parent on_enter if it exists
        if hasattr(super(), 'on_enter'):
            await super().on_enter()
    
   
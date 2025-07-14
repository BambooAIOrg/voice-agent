import asyncio
from livekit.agents import AgentSession, ConversationItemAddedEvent, FunctionToolsExecutedEvent
from livekit.agents.llm import ChatMessage as LivekitChatMessage
from bamboo_shared.logger import get_logger
from agents.vocab.service.message_service import MessageService
from agents.vocab.context import AgentContext

logger = get_logger(__name__)

class EventService:
    def __init__(self, context: AgentContext, session: AgentSession):
        self.context = context
        self.session = session
        self.message_service = context.message_service

    def init_event_handlers(self):
        @self.session.on("conversation_item_added")
        def on_conversation_item_added(event: ConversationItemAddedEvent):
            """Save messages when they are added to the conversation."""
            asyncio.create_task(self._handle_conversation_item_added(event))
        
        @self.session.on("function_tools_executed")
        def on_function_tools_executed(event: FunctionToolsExecutedEvent):
            """Save function calls and outputs when tools are executed."""
            asyncio.create_task(self._handle_function_tools_executed(event))


    async def _handle_conversation_item_added(self, event: ConversationItemAddedEvent):
        """Handle conversation item added event and save to database."""
        try:
            item = event.item
            
            # Check if item is a LiveKit ChatMessage
            if not isinstance(item, LivekitChatMessage):
                logger.debug(f"Skipping non-ChatMessage item: {type(item)}")
                return
            
            # Extract text content from the content list
            text_content = item.text_content
            
            if not text_content:
                return
            
            if item.role == "user":
                await self.message_service.save_user_message(text_content)
                logger.info(f"Saved user message: {text_content[:50]}...")
                
            elif item.role == "assistant":
                await self.message_service.save_assistant_message(
                    content=text_content,
                    phase=self.context.phase,
                    meta_data={
                        "word_id": self.context.word.id,
                        "word": self.context.word.word,
                        "agent_type": self.__class__.__name__,
                        "interrupted": getattr(item, 'interrupted', False)
                    }
                )
                logger.info(f"Saved assistant message: {text_content[:50]}...")
                
        except Exception as e:
            logger.error(f"Failed to save conversation item: {e}")
    
    async def _handle_function_tools_executed(self, event: FunctionToolsExecutedEvent):
        """Handle function tools executed event and save calls and outputs."""
        try:
            # Save function calls and their outputs
            for func_call, func_output in event.zipped():
                # Save function call
                await self.message_service.save_function_call_message(func_call)
                logger.info(f"Saved function call: {func_call.name}")
                
                if func_output:
                    # Save function output
                    await self.message_service.save_function_output_message(func_output)
                    logger.info(f"Saved function output for: {func_output.name}")
                
        except Exception as e:
            logger.error(f"Failed to save function tools execution: {e}")
